# cuckoos-nest

Claude Code on GitHub Copilot models. A small local bridge that speaks Anthropic's Messages API on one side and drives Copilot SDK sessions on the other.

```powershell
.\claude-copilot.ps1
```

That starts a bridge on a free localhost port, runs `claude` against it on `claude-opus-5.5`, and kills the bridge when `claude` exits.

## Why

I have a Copilot plan with a monthly AI credit allowance. Most of it goes unused. The people around me want Claude Code, not another harness. opencode has had an official Copilot login since January 2026, so it needs none of this. Claude Code has no Copilot provider, so it gets a bridge.

## How it works

Copilot does not hand out raw completions. The SDK gives you an agent session. Three session options make it behave enough like a model endpoint:

- `system_message` in `replace` mode, so Claude Code's system prompt replaces Copilot's.
- `available_tools` limited to client-declared tools, so none of Copilot's own tools run.
- Declared tools with no handler. The runtime then emits `external_tool.requested` and parks the turn until someone answers.

The bridge returns the parked calls to Claude Code as `tool_use` with `stop_reason: tool_use`. Claude Code runs the tools itself, with its own permission prompts, and sends the results in the next request. The bridge feeds them into the parked turn and streams what the model does next. A conversation stays on one Copilot session, so the prompt cache works: from the second call on, nearly the whole context is a cache read.

Only the documented SDK surface is used. No private endpoints, no token scraping.

## Requirements

- Windows with PowerShell 7. The bridge itself is plain Python, but the launcher is PowerShell and that is all I have tested.
- [uv](https://docs.astral.sh/uv/). The launcher runs `uv sync --frozen` on every start, so the first run sets up `.venv` from `uv.lock`.
- Claude Code on `PATH`.
- A Copilot login for your user (`copilot login`, or any Copilot CLI or SDK login on the machine).

## Usage

```powershell
.\claude-copilot.ps1                                # interactive, claude-opus-5.5
.\claude-copilot.ps1 -BridgeModel claude-sonnet-5   # cheaper main model
.\claude-copilot.ps1 -c                             # anything else goes to claude unchanged
.\claude-copilot.ps1 -p "fix the failing test"
.\claude-copilot.ps1 -BridgeStop                    # kill bridges left behind by a closed window
```

The launcher's own flags all start with `-Bridge`. It has no `param()` block on purpose: PowerShell would otherwise eat Claude Code's short flags like `-p` and `-c`. Each run gets its own bridge and port from 8790 up, so two sessions side by side do not interfere. Logs go to `logs/bridge-<date>-<port>.log`.

Mind you; Claude Code will warn that claude.ai connectors are disabled because another auth source is set. That is expected. I think it is the better default here: connectors would send mail and wiki content to Copilot's models.

## Limits

- Only `claude-*` models. On GPT models the Copilot runtime pairs parallel tool results by answer order, not by call id. Answered in reverse order, gpt-6-luna and gpt-6-sol swapped the results 3 of 3 times. The bridge answers in the model's order, but a wrong pairing gives the model another file's contents with no error anywhere, so GPT is refused until that is fixed. `check_tool_order.py` re-tests it and can mail you when a verdict changes.
- The bridge binds to loopback only and has no auth. It hands out commands that run on your machine - do not put it on a network.
- Esc in the middle of a turn, `/compact`, rewind and MCP servers that connect mid-session all end up on a fallback path: a fresh Copilot session with the earlier conversation flattened to text. That works, but it is lossy, and I have not measured how much worse it is.
- I have tested it headless (`claude -p`) with tools, follow-ups and subagents. I have not used the interactive TUI for real work yet.
- Thinking blocks are not passed through, and reasoning effort is not forwarded.
- I have not checked whether Copilot's terms cover this use. It is the documented SDK, but driving another vendor's harness is not what the docs describe.
- Tested on Copilot SDK 1.0.8 (pinned) and Claude Code 2.1.319. Both move fast. :-/

`docs/FEASIBILITY-2026-11-09.md` has the details and the numbers.

## Checking the GPT defect

```powershell
uv run check_tool_order.py
uv run check_tool_order.py --mail-script C:\path\to\send-mail.ps1
```

It runs the reverse-order probe five times per model and keeps the last verdict per model in `logs/tool-order/state.json`. The mail script is any PowerShell script that takes `-Subject` and `-Body` and exits 0. It is only called when a verdict changes.

## License

MIT.
