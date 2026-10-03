from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.harness import ClaudeAgent, ReferenceAgent, grade, load_tasks, markdown, prepare_workspace, run  # noqa: E402

TASKS = load_tasks()


def test_task_set_is_well_formed():
    assert len(TASKS) >= 8
    for task in TASKS:
        assert task["prompt"] and task["checks"] and task["reference"], task["id"]
        assert all(step["tool"].startswith("vixl_") for step in task["reference"])


@pytest.mark.parametrize("task", TASKS, ids=[t["id"] for t in TASKS])
def test_reference_solutions_pass(task):
    results, summary = run([task], ReferenceAgent())
    result = results[0]
    assert result["passed"], [c for c in result["checks"] if not c["passed"]]
    assert result["tool_errors"] == 0


class Idle:
    name = "idle"

    def run(self, task, tools):
        return {"round_trips": 0, "usage": {}, "trace": []}


def test_doing_nothing_fails_every_task():
    results, summary = run(TASKS, Idle())
    assert summary["passed"] == 0
    assert "FAIL" in markdown(results, summary, {"agent": "idle"})


def test_setup_documents_start_broken(tmp_path):
    task = next(t for t in TASKS if t["id"] == "fix-layout")
    prepare_workspace(task, tmp_path)
    checks = {c["check"]: c["passed"] for c in grade(task, tmp_path)}
    assert checks["no design errors"] is False and checks["title kept"] is True


def block(**fields):
    return SimpleNamespace(**fields)


class ScriptedMessages:
    """Plays back assistant turns and records each request, like messages.create."""

    def __init__(self, turns):
        self.turns, self.requests = list(turns), []

    def create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        content, stop = self.turns.pop(0)
        usage = block(input_tokens=100, output_tokens=20, cache_read_input_tokens=50, cache_creation_input_tokens=0)
        return block(content=content, stop_reason=stop, usage=usage)


def test_claude_agent_loop_runs_tools_and_keeps_history_append_only():
    task = next(t for t in TASKS if t["id"] == "equal-spacing")
    create = task["reference"][0]["arguments"]
    apply = task["reference"][1]["arguments"]
    turns = [
        (
            [
                block(type="thinking", thinking="", signature="sig"),
                block(type="tool_use", id="t1", name="vixl_document_create", input=create),
            ],
            "tool_use",
        ),
        (
            [
                block(type="tool_use", id="t2", name="vixl_operations_apply", input=apply),
                block(type="tool_use", id="t3", name="vixl_render_preview", input={"max_width": 256}),
                block(type="tool_use", id="t4", name="vixl_operations_apply", input={"operations": [{"type": "mvoe"}]}),
            ],
            "tool_use",
        ),
        ([block(type="text", text="Done.")], "end_turn"),
    ]
    messages = ScriptedMessages(turns)
    client = block(beta=block(messages=messages), messages=messages)
    agent = ClaudeAgent(client=client, effort="low")
    result = run([task], agent)[0][0]
    assert result["passed"] and result["round_trips"] == 3
    assert result["tool_calls"] == 4 and result["tool_errors"] == 1
    assert result["usage"]["input_tokens"] == 300 and result["usage"]["cache_read_input_tokens"] == 150
    first, second, third = messages.requests
    assert first["model"] == "claude-opus-5-5" and first["fallbacks"] == "default"
    assert first["betas"] == ["server-side-fallback-2026-07-01"] and first["output_config"] == {"effort": "low"}
    assert first["cache_control"] == {"type": "ephemeral"}
    assert any(tool["name"] == "vixl_check" for tool in first["tools"])
    # The assistant turn (including its thinking block) is appended unchanged.
    assert second["messages"][1]["content"] is turns[0][0]
    # Parallel tool calls come back as one user message with every result.
    results = third["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["t2", "t3", "t4"]
    assert results[1]["content"][0]["type"] == "image"
    assert results[2]["is_error"] and "unknown_operation" in results[2]["content"][0]["text"]
    assert result["final"] == "Done."


def test_claude_agent_stops_on_refusal():
    task = TASKS[0]
    messages = ScriptedMessages([([], "refusal")])
    agent = ClaudeAgent(client=block(beta=block(messages=messages), messages=messages), fallbacks=False)
    result = run([task], agent)[0][0]
    assert not result["passed"] and result["stop_reason"] == "refusal" and result["round_trips"] == 1
    assert "fallbacks" not in messages.requests[0]
