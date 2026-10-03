# Agent evaluation suite

Vixl is used mostly by AI agents, so the test that matters most is whether an agent can finish
real design briefs through the MCP tools, and at what cost. This suite measures that.

Each task in `tasks/` is a JSON file with:

- `prompt` — the brief given to the agent, exactly as a user might write it;
- `setup` — optional starting files (generated images, pre-built `.vixl` documents with history);
- `checks` — programmatic success criteria evaluated on the files the agent leaves behind
  (`canvas`, `layer`, `design` (runs `check_design`), `spacing`, `centered`, `layer_field`,
  `variable`, `file`, `files_differ`, `assert`);
- `reference` — a scripted tool-call solution, used to prove the task is solvable and the checks
  are correct.

The harness (`harness.py`) starts the real MCP server in-process on a fresh temporary workspace
per task, runs an agent, grades the workspace, and records:

| Metric | Meaning |
| --- | --- |
| success | every check passed |
| round trips | model calls (one per assistant turn) |
| tool calls / tool errors | MCP calls made, and how many returned an error |
| tool result tokens | approximate size of what the tools sent back (chars ÷ 4) |
| input / output tokens | from the API's usage, including cache reads |

## Running

```bash
pip install -e ".[dev]"

# Offline: replay reference solutions (no API key, also runs in pytest/CI)
python -m evals.run

# Claude through the official Anthropic SDK (spends API credits)
export ANTHROPIC_API_KEY=...        # or `ant auth login`
python -m evals.run --agent claude
python -m evals.run --agent claude --model claude-sonnet-5-5 --effort low --schema slim --tasks "photo-*"
```

Results go to `eval-results/results.json` (full traces) and `eval-results/report.md`; `--keep`
also saves each task's final workspace files for inspection. The **Agent eval** GitHub workflow
runs the same command on demand with the `ANTHROPIC_API_KEY` repository secret and uploads the
results.

The Claude agent uses a manual tool-use loop: assistant turns are appended unchanged (so thinking
blocks stay valid), parallel tool results return in a single user message, prompt caching is on,
and server-side refusal fallbacks (`fallbacks: "default"`) are enabled unless `--no-fallbacks`.

## Using it

Run the suite before and after changing tool descriptions, schemas, error messages, response
formats or normalization rules, and compare success rate, round trips and tokens. Run it with
`--schema full` and `--schema slim` to decide which mode suits a given model. When agents fail a
task, read the trace in `results.json`: repeated tool errors usually point at a confusing schema
or message, which is a product bug.

## Adding tasks

Write the brief the way a person would, keep checks objective (geometry, text, files, design
checks — not taste), include a reference solution, and run `pytest tests/test_eval_harness.py`:
it verifies that the reference passes and that an idle agent fails.
