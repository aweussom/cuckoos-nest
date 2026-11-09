# cuckoos-nest

Claude Code on GitHub Copilot models. A small local bridge that speaks Anthropic's Messages API on one side and drives Copilot SDK sessions on the other.

```powershell
.\claude-copilot.ps1
```

That starts a bridge on a free localhost port, runs `claude` against it on `claude-opus-5.5`, and kills the bridge when `claude` exits.

## Do you need this?

Probably not. Check these first:

1. GitHub's own Copilot CLI. Native client, needs nothing extra.
2. If you do not like the Copilot CLI, use [opencode](https://opencode.ai). GitHub has supported Copilot login in opencode officially since January 2026: run `opencode auth login`, pick GitHub Copilot, and every Copilot model shows up as `github-copilot/...`. I run opencode 2.2.6 that way. It talks to Copilot directly, not through the SDK this repo uses, so the GPT result-pairing problem below does not apply. Quick test with gpt-6-luna: it paired parallel tool results correctly 3 of 3 times. This is the setup I'd recommend.
3. This repo is for people who want Claude Code itself on Copilot models, and nothing else will do.

## Why

I have a Copilot plan with a monthly AI credit allowance. Most of it goes unused. The people around me want Claude Code, not another harness. Claude Code has no Copilot provider, so it gets a bridge.

## How it works

Copilot does not hand out raw completions. The SDK gives you an agent session. Three session options make it behave enough like a model endpoint:

- `system_message` in `replace` mode, so Claude Code's system prompt replaces Copilot's.
- `available_tools` limited to client-declared tools, so none of Copilot's own tools run.
- Declared tools with no handler. The runtime then emits `external_tool.requested` and parks the turn until someone answers.

The bridge returns the parked calls to Claude Code as `tool_use` with `stop_reason: tool_use`. Claude Code runs the tools itself, with its own permission prompts, and sends the results in the next request. The bridge feeds them into the parked turn and streams what the model does next. A conversation stays on one Copilot session, so the prompt cache works: from the second call on, nearly the whole context is a cache read.

Only the documented SDK surface is used. No private endpoints, no token scraping.

## Install

Double-click `install-windows.bat`, or run it from a terminal. It checks for PowerShell 7, uv, Claude Code and the Copilot CLI, and offers to install whatever is missing through winget. It sets up the Python environment from `uv.lock` and offers to run `copilot login`. It asks before it installs anything, and it is safe to run again.

It refuses to install from a folder inside OneDrive, with a space in the path, or with a path longer than 60 characters. Python environments break in those places in ways I do not want to debug. Move the folder to `C:\cuckoos-nest` and run it there.

If you already have PowerShell 7, uv, Claude Code and a Copilot login, skip it. The launcher runs `uv sync --frozen` on every start anyway.

I've only tested this on Windows 11. The bridge itself is plain Python, but the launcher is PowerShell.

## Usage

From the project you want to work on:

```powershell
C:\cuckoos-nest\claude-copilot.cmd                                # interactive, claude-opus-5.5
C:\cuckoos-nest\claude-copilot.cmd -BridgeModel claude-sonnet-5   # cheaper main model
C:\cuckoos-nest\claude-copilot.cmd -c                             # anything else goes to claude unchanged
C:\cuckoos-nest\claude-copilot.cmd -p "fix the failing test"
C:\cuckoos-nest\claude-copilot.cmd -BridgeStop                    # kill bridges left behind by a closed window
```

`claude-copilot.cmd` runs `claude-copilot.ps1` with execution policy bypassed, so it also works from cmd and on machines where downloaded scripts are blocked. From PowerShell 7 you can call the `.ps1` directly.

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
