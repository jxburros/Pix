"""Agent evaluation harness for Vixl's MCP tools.

Each task gives an agent a natural-language design brief and a fresh workspace, lets it work
through the real MCP server (in-process), then grades the resulting files with programmatic
checks. Results record success, model round trips, tool calls, tool errors and token usage, so
changes to tool descriptions, schemas, errors or responses can be measured instead of guessed.

Agents:
  reference  replays each task's scripted reference solution (offline; validates tasks + harness)
  claude     drives the tools with Claude through the official Anthropic SDK
"""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time

from PIL import Image

TASK_DIR = Path(__file__).parent / "tasks"
SYSTEM_PROMPT = (
    "You are a design agent working through Vixl's image-editing tools in a sandboxed workspace. "
    "Complete the user's brief end to end: create or open documents, apply operations, verify the "
    "result with vixl_check and vixl_render_preview, fix problems, and export files when asked. "
    "Use workspace-relative paths. When the brief is fully done, reply with a one-line summary."
)


# --- tasks ---------------------------------------------------------------------------------------


def load_tasks(directory=TASK_DIR, pattern="*"):
    tasks = []
    for path in sorted(Path(directory).glob(f"{pattern}.json")):
        task = json.loads(path.read_text(encoding="utf-8"))
        task.setdefault("id", path.stem)
        tasks.append(task)
    return tasks


def prepare_workspace(task, workspace):
    """Create the task's starting files: generated images and pre-built documents."""
    from vixl import Project

    for spec in task.get("setup", {}).get("images", []):
        image = Image.new("RGB", (spec["width"], spec["height"]), spec.get("color", "gray"))
        if spec.get("gradient"):
            top, bottom = Image.new("RGB", image.size, spec["gradient"][0]), Image.new("RGB", image.size, spec["gradient"][1])
            mask = Image.linear_gradient("L").resize(image.size)
            image = Image.composite(bottom, top, mask)
        image.save(workspace / spec["path"])
    for spec in task.get("setup", {}).get("documents", []):
        project = Project(spec["width"], spec["height"], spec.get("background", "transparent"))
        for batch in spec.get("batches", []):
            project.apply(batch)
        project.save(workspace / spec["path"])


# --- grading -------------------------------------------------------------------------------------


def _matches(layer, match):
    for key, expected in match.items():
        if key == "text_contains":
            if expected.lower() not in str(layer.get("text", "")).lower():
                return False
        elif key == "min_size":
            if layer.get("size", 0) < expected:
                return False
        elif key in ("min_width", "min_height"):
            if layer.get(key[4:], 0) < expected:
                return False
        elif key == "type":
            if layer.get("type") not in (expected if isinstance(expected, list) else [expected]):
                return False
        elif layer.get(key) != expected:
            return False
    return True


def grade(task, workspace):
    """Run every check in ``task["checks"]``; return a list of {check, passed, detail}."""
    from vixl import Project, VixlError
    from vixl.validation import assert_rule

    results = []
    documents = {}

    def document(path):
        if path not in documents:
            documents[path] = Project.load(workspace / path)
        return documents[path]

    for check in task["checks"]:
        kind = check["type"]
        passed, detail = False, None
        try:
            if kind == "file":
                path = workspace / check["path"]
                passed = path.is_file()
                if passed and check.get("image_size"):
                    with Image.open(path) as image:
                        detail = list(image.size)
                        passed = detail == check["image_size"]
            elif kind == "files_differ":
                first, second = (workspace / path for path in check["paths"])
                passed = first.is_file() and second.is_file() and first.read_bytes() != second.read_bytes()
            else:
                project = document(check.get("document", task.get("document")))
                state = project.inspect()
                layers = state["layers"]
                if kind == "canvas":
                    detail = [state["canvas"]["width"], state["canvas"]["height"]]
                    passed = detail == [check["width"], check["height"]]
                elif kind == "layer":
                    found = [x for x in layers if _matches(x, check.get("match", {}))]
                    detail = [x["name"] for x in found]
                    passed = len(found) >= check.get("min", 1) and len(found) <= check.get("max", 10**6)
                    region = check.get("within")
                    if passed and region:
                        x, y, w, h = region
                        passed = any(
                            b[0] >= x and b[1] >= y and b[0] + b[2] <= x + w and b[1] + b[3] <= y + h
                            for b in (layer["resolved_bounds"] for layer in found)
                        )
                elif kind == "design":
                    report = project.check(**check.get("options", {}))
                    detail = [issue["message"] for issue in report["issues"] if issue["severity"] == "error"]
                    passed = report["passed"]
                elif kind == "spacing":
                    report = project.measure_spacing(**check["options"])
                    detail = [gap["pixels"] for gap in report["gaps"]]
                    passed = report["passed"]
                elif kind == "variable":
                    detail = state["variables"].get(check["variable"])
                    passed = detail == check["equals"]
                elif kind == "layer_field":
                    detail = project.layer(check["layer"]).get(check["field"])
                    passed = detail == check["equals"]
                elif kind == "assert":
                    detail = [rule for rule in check["rules"] if not assert_rule(project, rule)]
                    passed = not detail
                elif kind == "centered":
                    target = project.layer(check["layer"])
                    x, y, w, h = project.inspect(target["id"])["resolved_bounds"]
                    c = state["canvas"]
                    offsets = [abs(x + w / 2 - c["width"] / 2), abs(y + h / 2 - c["height"] / 2)]
                    axes = check.get("axes", ["x", "y"])
                    detail = offsets
                    passed = all(offsets[i] <= check.get("tolerance", 2) for i, a in enumerate(("x", "y")) if a in axes)
                else:
                    raise ValueError(f"Unknown check type {kind!r}")
        except (VixlError, OSError, KeyError, ValueError) as exc:
            detail = f"{type(exc).__name__}: {exc}"
        results.append({"check": check.get("name", kind), "passed": bool(passed), "detail": detail})
    return results


# --- tool plumbing -------------------------------------------------------------------------------


class Tools:
    """Synchronous wrapper around an in-process Vixl MCP server."""

    def __init__(self, workspace, schema="full"):
        from vixl.interfaces import mcp_server

        self.server = mcp_server(workspace=workspace, schema=schema)
        self.loop = asyncio.new_event_loop()
        self.calls = 0
        self.errors = 0
        self.result_chars = 0

    def definitions(self):
        tools = self.loop.run_until_complete(self.server.list_tools())
        return [{"name": t.name, "description": t.description or "", "input_schema": t.inputSchema} for t in tools]

    def call(self, name, arguments):
        """Return (is_error, blocks) where blocks are Anthropic-style text/image content blocks."""
        self.calls += 1
        try:
            result = self.loop.run_until_complete(self.server.call_tool(name, arguments))
        except Exception as exc:  # ToolError and validation failures become error results
            self.errors += 1
            text = str(exc)
            self.result_chars += len(text)
            return True, [{"type": "text", "text": text}]
        content = result[0] if isinstance(result, tuple) else result
        blocks = []
        for item in content:
            if getattr(item, "type", None) == "image":
                blocks.append(
                    {"type": "image", "source": {"type": "base64", "media_type": item.mimeType, "data": item.data}}
                )
            else:
                text = getattr(item, "text", "")
                self.result_chars += len(text)
                blocks.append({"type": "text", "text": text})
        return False, blocks or [{"type": "text", "text": "(no output)"}]

    def close(self):
        self.loop.close()


# --- agents --------------------------------------------------------------------------------------


class ReferenceAgent:
    """Replays the task's scripted solution. Fails the run if any scripted call errors."""

    name = "reference"

    def run(self, task, tools):
        trace = []
        for step in task.get("reference", []):
            failed, blocks = tools.call(step["tool"], step.get("arguments", {}))
            trace.append({"tool": step["tool"], "error": failed, "output": _text(blocks)[:500]})
        return {"round_trips": len(task.get("reference", [])), "trace": trace, "usage": {}}


class ClaudeAgent:
    """Manual tool-use loop through the official Anthropic SDK (append-only history)."""

    name = "claude"

    def __init__(self, model="claude-opus-5-5", effort=None, max_turns=40, fallbacks=True, client=None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client, self.model, self.effort = client, model, effort
        self.max_turns, self.fallbacks = max_turns, fallbacks

    def create(self, **arguments):
        if self.effort:
            arguments["output_config"] = {"effort": self.effort}
        if self.fallbacks:
            return self.client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **arguments
            )
        return self.client.messages.create(**arguments)

    def run(self, task, tools):
        definitions = tools.definitions()
        messages = [{"role": "user", "content": task["prompt"]}]
        usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        trace, turns, stop = [], 0, None
        while turns < self.max_turns:
            turns += 1
            response = self.create(
                model=self.model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                tools=definitions,
                messages=messages,
                cache_control={"type": "ephemeral"},
            )
            for key in usage:
                usage[key] += getattr(response.usage, key, 0) or 0
            stop = response.stop_reason
            # Append the assistant turn exactly as returned so thinking blocks stay valid.
            messages.append({"role": "assistant", "content": response.content})
            if stop == "refusal":
                break
            uses = [block for block in response.content if block.type == "tool_use"]
            if stop != "tool_use" or not uses:
                if stop == "pause_turn":
                    continue
                break
            results = []
            for use in uses:
                failed, blocks = tools.call(use.name, use.input)
                trace.append({"tool": use.name, "input": use.input, "error": failed, "output": _text(blocks)[:500]})
                results.append({"type": "tool_result", "tool_use_id": use.id, "content": blocks, "is_error": failed})
            # All results for one assistant turn go back in a single user message.
            messages.append({"role": "user", "content": results})
        final = next((b.text for b in messages[-1]["content"] if getattr(b, "type", None) == "text"), "") if messages[-1]["role"] == "assistant" else ""
        return {"round_trips": turns, "stop_reason": stop, "usage": usage, "trace": trace, "final": final}


def _text(blocks):
    return " ".join(block.get("text", "[image]") for block in blocks)


# --- running ---------------------------------------------------------------------------------------


def run_task(task, agent, schema="full", keep=None):
    with tempfile.TemporaryDirectory(prefix=f"vixl-eval-{task['id']}-") as directory:
        workspace = Path(directory)
        prepare_workspace(task, workspace)
        tools = Tools(workspace, schema=schema)
        started = time.monotonic()
        error = None
        try:
            outcome = agent.run(task, tools)
        except Exception as exc:  # A crashed agent run is a failed task, not a crashed eval.
            outcome, error = {"round_trips": 0, "usage": {}, "trace": []}, f"{type(exc).__name__}: {exc}"
        finally:
            tools.close()
        checks = grade(task, workspace)
        if keep:
            target = Path(keep) / task["id"]
            target.mkdir(parents=True, exist_ok=True)
            for path in workspace.iterdir():
                if path.is_file() and not path.name.endswith(".lock"):
                    (target / path.name).write_bytes(path.read_bytes())
        return {
            "task": task["id"],
            "agent": agent.name,
            "passed": error is None and all(c["passed"] for c in checks),
            "checks": checks,
            "round_trips": outcome["round_trips"],
            "tool_calls": tools.calls,
            "tool_errors": tools.errors,
            "tool_result_tokens_estimate": tools.result_chars // 4,
            "usage": outcome.get("usage", {}),
            "seconds": round(time.monotonic() - started, 2),
            "error": error,
            "stop_reason": outcome.get("stop_reason"),
            "final": outcome.get("final"),
            "trace": outcome.get("trace", []),
        }


def summarize(results):
    count = len(results) or 1
    total = {key: sum(r["usage"].get(key, 0) for r in results) for key in ("input_tokens", "output_tokens")}
    return {
        "tasks": len(results),
        "passed": sum(r["passed"] for r in results),
        "success_rate": round(sum(r["passed"] for r in results) / count, 3),
        "mean_round_trips": round(sum(r["round_trips"] for r in results) / count, 2),
        "mean_tool_calls": round(sum(r["tool_calls"] for r in results) / count, 2),
        "tool_error_rate": round(sum(r["tool_errors"] for r in results) / max(1, sum(r["tool_calls"] for r in results)), 3),
        "mean_tool_result_tokens": round(sum(r["tool_result_tokens_estimate"] for r in results) / count),
        **{f"total_{key}": value for key, value in total.items()},
    }


def markdown(results, summary, meta):
    lines = [
        f"# Vixl agent eval — {meta.get('agent')} {meta.get('model') or ''}".rstrip(),
        "",
        f"Success **{summary['passed']}/{summary['tasks']}** ({summary['success_rate']:.0%}) · "
        f"round trips {summary['mean_round_trips']} · tool calls {summary['mean_tool_calls']} · "
        f"tool error rate {summary['tool_error_rate']:.1%} · tool result tokens ≈{summary['mean_tool_result_tokens']}/task",
        "",
        "| Task | Result | Round trips | Tool calls | Tool errors | Input tok | Output tok | Failed checks |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in results:
        failed = ", ".join(c["check"] for c in r["checks"] if not c["passed"]) or ("error: " + r["error"] if r["error"] else "")
        lines.append(
            f"| {r['task']} | {'pass' if r['passed'] else 'FAIL'} | {r['round_trips']} | {r['tool_calls']} | "
            f"{r['tool_errors']} | {r['usage'].get('input_tokens', '–')} | {r['usage'].get('output_tokens', '–')} | {failed} |"
        )
    return "\n".join(lines) + "\n"


def run(tasks, agent, schema="full", keep=None):
    results = [run_task(deepcopy(task), agent, schema, keep) for task in tasks]
    return results, summarize(results)

