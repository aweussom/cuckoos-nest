# CLAUDE.md

Guidance for Claude Code and other agents working in this repository.

## What this repo is

A local bridge that lets Claude Code run on GitHub Copilot models. `bridge.py`
serves Anthropic's `/v1/messages` and drives Copilot SDK sessions behind it;
`claude-copilot.ps1` starts one bridge per Claude Code session and tears it
down afterwards. `probe_tool_order.py` and `check_tool_order.py` watch a
Copilot runtime defect that decides which models are allowed.

Read `STATUS.md` first (what is true today) and `TODONT.md` before proposing
anything structural. `docs/FEASIBILITY-2026-11-09.md` has the mechanism and
the measurements.

## Rules that bite here

- **Loopback only.** The bridge hands out tool calls that the harness runs on
  this machine, with no auth in front. `--host` refuses anything but
  loopback. Do not add a LAN option.
- **Verified models only.** `VERIFIED_MODEL_PREFIXES` in `bridge.py` is the
  allowlist (`claude-` today). GPT models pair parallel tool results by answer
  order in the Copilot runtime; a wrong pairing gives the model another
  file's contents with no error anywhere. Widen the list only on a
  `check_tool_order.py` verdict of `fixed`.
- **Answer parked tool calls in the model's order,** one at a time. The loop
  in `plan_request` says why. Do not parallelise or reorder it.
- **The launcher has no `param()` block** and never calls `Set-Location`.
  Both are deliberate; `TODONT.md` has what went wrong otherwise.
- **Kill the process tree** (`taskkill /T`). The bridge runs as a child of
  `uv run` and of the venv's launcher stub.
- **No employer names, internal hostnames or personal paths** in anything
  committed. This repo is public.

## Validation

```powershell
uv sync --frozen
uv run python -m py_compile bridge.py probe_tool_order.py check_tool_order.py
uv run probe_tool_order.py claude-sonnet-5 8 reverse   # live, a few Copilot credits
.\claude-copilot.ps1 -p "Reply with the single word READY."
```

There are no offline tests yet. Every check above talks to the live Copilot
runtime and spends AI credits. A change to `bridge.py` is validated by a
`claude-copilot.ps1 -p` run that uses tools (Read, Edit, Bash), then checking
`logs/bridge-<date>-<port>.log` for `fresh` / `resume` / `continue`.

## Writing

- Non-trivial claims in `STATUS.md`, `TODONT.md` and `docs/` carry
  `[DOCUMENTED <source>]`, `[OBSERVED <date>]`, `[INFERRED]` or `[GUESS]`.
- Versions, CLI flags and API surfaces are looked up or measured before they
  are written down.
- `STATUS.md` is replaced, never appended to. `TODONT.md` gets an entry when
  something fails, with the numbers.
- Code style: flat control flow, named intermediates, fail loud, log the
  intention before the action, `file:line` on every log line.
