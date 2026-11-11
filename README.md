# cuckoos-nest

Claude Code on GitHub Copilot models. A small local bridge that speaks Anthropic's Messages API on one side and drives Copilot SDK sessions on the other.

```powershell
.\claude-copilot.ps1
```

That starts a bridge on a free localhost port, runs `claude` against it on `claude-opus-5.5`, and kills the bridge when `claude` exits.

## Do you need this?

Probably not. Check these first:

1. GitHub's own Copilot CLI. It has gotten a lot better the last six months, and I have no problem at all using it instead of Claude Code. Native client, needs nothing extra.
2. If you do not like the Copilot CLI, use [opencode](https://opencode.ai). GitHub has officially supported Copilot login in opencode since January 2026: run `opencode auth login`, pick GitHub Copilot, and every Copilot model shows up as `github-copilot/...`. I run opencode 2.2.6 that way. It talks to Copilot directly, not through the SDK this repo uses, so the pairing problem below never applied to it. Quick test with gpt-6-luna: it paired parallel tool results correctly 3 of 3 times. That's the setup I'd recommend.
3. This repo is for people who will NOT use the Copilot CLI or opencode, and want Claude Code itself on Copilot models.

## Why

I have a Copilot plan with a monthly AI credit allowance. Most of it goes unused. The people around me want Claude Code, not another harness. Claude Code has no Copilot provider, so it gets a bridge. Or a nest, if you'd like.

## How it works

Copilot does not hand out raw completions. The SDK gives you an agent session. Three session options make it behave enough like a model endpoint:

- `system_message` in `replace` mode, so Claude Code's system prompt replaces Copilot's.
- `available_tools` limited to client-declared tools, so none of Copilot's own tools run.
- Declared tools with no handler. The runtime then emits `external_tool.requested` and parks the turn until someone answers.

The bridge returns the parked calls to Claude Code as `tool_use` with `stop_reason: tool_use`. Claude Code runs the tools itself, with its own permission prompts, and sends the results in the next request. The bridge feeds them into the parked turn and streams what the model does next. A conversation stays on one Copilot session, so the prompt cache works: from the second call on, nearly the whole context is a cache read.

The session survives `/model` (the bridge calls `set_model` on it) and tools that Claude Code loads in the middle of a session, such as a deferred tool found by ToolSearch (the bridge re-registers the session with the new tool list). Before 2026-11-10 both of those dropped the session and fell back to the lossy path below, on every request after.

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
C:\cuckoos-nest\claude-copilot.cmd -BridgeSmallModel claude-sonnet-5  # model for Sonnet, Haiku and background calls
C:\cuckoos-nest\claude-copilot.cmd -BridgePort 8800               # first port to try (default 8790)
C:\cuckoos-nest\claude-copilot.cmd -c                             # anything else goes to claude unchanged
C:\cuckoos-nest\claude-copilot.cmd -p "fix the failing test"
C:\cuckoos-nest\claude-copilot.cmd -BridgeStop                    # kill bridges left behind by a closed window
```

Claude Code asks for Anthropic model ids. The bridge maps them: Opus to `-BridgeModel`, Sonnet and Haiku (and with them most subagents) to `-BridgeSmallModel`, which defaults to `claude-sonnet-5`. A model with no Copilot match, Fable for instance, gets a 400 that says so. Before 2026-11-10 it quietly got the default model, and the status line said Fable while Opus answered.

`claude-copilot.cmd` runs `claude-copilot.ps1` with execution policy bypassed, so it also works from cmd and on machines where downloaded scripts are blocked. From PowerShell 7 you can call the `.ps1` directly.

The launcher's own flags all start with `-Bridge`. It has no `param()` block on purpose: PowerShell would otherwise eat Claude Code's short flags like `-p` and `-c`. Each run gets its own bridge and the first free port of 20, from 8790 up, so two sessions side by side do not interfere. With all 20 taken it stops and suggests `-BridgeStop`. The port is reserved with a pid file the moment it is picked, so two sessions started together get different ports. `-BridgeStop` only kills a bridge whose session is gone and whose pid still belongs to a bridge; a pid file left from before a reboot is just removed.

When claude exits it prints `claude --resume <id>`. That goes to Anthropic, not through the bridge. To carry on on Copilot, run `claude-copilot.cmd --resume <id>`; the launcher says so under claude's line. Logs go to `logs/bridge-<date>-<time>-<port>.log`, one per run.

Two environment variables for the bridge:

- `BRIDGE_DUMP_DIR=<dir>` writes every request Claude Code sends as JSON. For debugging. The files hold your prompts and file contents.
- `BRIDGE_ALLOW_UNVERIFIED=1` lets unverified models through (anything that is not `claude-*` or `gpt-*`). Do not. See Limits for why they are refused.

The launcher also sets two variables for claude:

- `CLAUDE_CODE_AUTO_MODE_SERVER=0`, so auto mode works. See below.
- `ENABLE_CLAUDEAI_MCP_SERVERS=false`. claude.ai connectors cannot load when an API key is set, and Claude Code would warn about it at every start. I think it is the better default anyway: connectors would send mail and wiki content to Copilot's models.

### Auto mode

Auto mode has a separate classifier model that judges actions before they run. By default Claude Code asks Anthropic's server to do that inside the normal model requests. Through the bridge nothing answers, and an action without a verdict is refused, without asking you. With `CLAUDE_CODE_AUTO_MODE_SERVER=0` Claude Code sends its own classifier requests instead. They go through the bridge to the small model, claude-sonnet-5, like any other call.

I have tested that headless: `curl` to example.com, a POST of the README to httpbin and a push to a temporary branch were allowed, a force push was stopped by a deny rule in my settings. I have not seen the classifier itself block something through the bridge. One push-delete was blocked in a session on Anthropic's API and allowed through the bridge, but the second prompt asked for the delete outright, so that says little.

Each check sends the classifier's own system prompt, about 48,000 tokens. The second check onward is a cache read, about 1 credit on Sonnet 5; a cold cache costs about 12. Shell commands and network calls get checked; reads and edits in the working directory do not.

## Limits

- Only `claude-*` and `gpt-*` models. With Copilot CLI 1.0.73 (what SDK 1.0.8 bundles) the runtime paired parallel tool results on GPT models by answer order, not by call id. Answered in reverse order, gpt-6-luna and gpt-6-sol swapped the results 3 of 3 times. A wrong pairing gives the model another file's contents with no error anywhere, so I refused GPT. I was on an old SDK. On 1.0.30 (CLI 1.0.108) I have not seen a swap: gpt-6-luna 12 of 13 correct, gpt-6-sol 13 of 13, and the odd one was an incomplete answer. GPT is allowed since 2026-11-10, with one headless run with tools on gpt-6-luna behind it. Claude Code does not know the GPT model names and assumes a 200k context window. Other models stay out until the check says ok for them. `check_tool_order.py` re-tests it and can mail you when a verdict changes.
- The bridge binds to loopback only. It hands out commands that run on your machine - do not put it on a network. The launcher makes a random token per run and the bridge refuses requests without it, so other local programs and web pages that post to 127.0.0.1 get a 401. Before 2026-11-10 there was no token.
- Esc in the middle of a turn, `/compact` and rewind end up on a fallback path: a fresh Copilot session with the earlier conversation flattened to text. That works, but it is lossy, and I have not measured how much worse it is. It also costs more, because the whole history is written to the cache again.
- Auto mode works only with the client-side classifier, which the launcher turns on. Run `claude` against the bridge some other way and it refuses every action it would check.
- WebSearch does not work. It is a server tool that runs on Anthropic's side. The bridge refuses it with a 400 that says so, and the model tells you. Copilot has its own Bing search, which an account admin can turn off (mine is), and the bridge does not use it.
- I have tested it headless (`claude -p`) with tools, follow-ups and subagents, and in the interactive TUI for a few short sessions with my own `~/.claude` setup (global CLAUDE.md, skills, MCP tools loaded through ToolSearch). Not for an hour of real work yet. My hooks run (a small tab-colour tool on every prompt and tool call); one of them hit its 5 s timeout twice, which I have not tracked down. Actual MCP tool calls are untested.
- Thinking blocks are not passed through, and reasoning effort is not forwarded.
- I have not checked whether Copilot's terms cover this use. It is the documented SDK, but driving another vendor's harness is not what the docs describe.
- Pinned to Copilot SDK 1.0.30 since 2026-11-10. Most of the testing below was on 1.0.8 and Claude Code 2.1.319. Both move fast. :-/

`docs/FEASIBILITY-2026-11-09.md` has the details and the numbers.

## Cost

Copilot bills per token in AI credits, 1 credit = $0.01. From [GitHub's pricing page](https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing), read 2026-11-10, per million tokens:

| Model | Input | Cached input | Cache write | Output |
|---|---|---|---|---|
| claude-opus-5.5 | $4.00 | $0.20 | $5.00 | $20.00 |
| claude-sonnet-5 | $2.00 | $0.20 | $2.50 | $10.00 |

Sonnet is half price on everything but cached input, which is what `-BridgeModel claude-sonnet-5` is for. A cache read is a twentieth of fresh input on Opus, so a session that stays on one Copilot session is a lot cheaper than one that keeps falling back. The page does not say which plans include which models; check your own model list. Prices change, so check the page before you trust the table.

## Uninstall

Delete the folder. Everything the bridge makes lives inside it: `.venv`, `logs/`, and `.copilot-runtime/` if you run a Microsoft Store Python. The installer's winget packages (PowerShell 7, uv, Claude Code, the Copilot CLI) are ordinary packages; remove them with `winget uninstall` if you do not want them. The `copilot login` lives in your user profile, not in this folder, and the CLI I have has no logout command.

## Checking tool-result pairing

```powershell
uv run check_tool_order.py
uv run check_tool_order.py --mail-script C:\path\to\send-mail.ps1
```

It runs the reverse-order probe five times per model and keeps the last verdict per model in `logs/tool-order/state.json`: `ok` (all five paired correctly), `broken` (at least one swap) or `inconclusive` (no swap, but a run gave no usable answer, usually a model that did not make both calls in time). The mail script is any PowerShell script that takes `-Subject` and `-Body` and exits 0. It is only called when a verdict changes.

## Testing

There is one offline test, `tests/test_matching.py`, for how requests are matched to conversations. Everything else below talks to the live Copilot runtime and spends a few AI credits per run.

What I have run, on Windows 11 with Copilot SDK 1.0.8 and Claude Code 2.1.319, headless (`claude -p`) unless it says otherwise. On SDK 1.0.30 I have only run the pairing check and a headless run with parallel Reads, Edit and Bash, once on claude-opus-5.5 and once on gpt-6-luna:

- A bug fix in a small repo: Bash, two parallel Reads, Edit, Bash again. Passed, on gpt-6-luna, before GPT was refused. Not re-run on a Claude model.
- A new function with tests on claude-opus-5.5, then a follow-up with `-c` that stayed on the same Copilot session. Passed.
- A subagent, in the foreground and in the background, mapped to claude-sonnet-5. Passed.
- A turn parked for 420 s before the tool results came back. It resumed normally. Also on gpt-6-luna.
- Interactive TUI, a few short sessions with tools: a `/model` switch from Opus to Sonnet and WebSearch being loaded mid-session, all on one Copilot session; Fable refused with a 400; WebSearch refused with a 400.
- Two `claude-copilot` sessions started one second apart. They got ports 8790 and 8791, and both bridges were gone afterwards.
- `install-windows.bat` on a machine that already had everything, and from a 116-character path, where it refused as it should.
- `install-windows.bat` on a clean Windows Sandbox, all the way from no winget to a signed-in Copilot, then `claude-copilot.cmd -p` and one short interactive session with a tool call. Passed on the second try. The first run found two places where winget put things somewhere I did not expect (see `TODONT.md`).

Not run yet: the interactive TUI on real work, Esc in the middle of a turn, `/compact`, and images in tool results.

Quick checks after a change:

```powershell
uv run python -m py_compile bridge.py probe_tool_order.py check_tool_order.py
uv run python tests/test_matching.py
uv run probe_tool_order.py claude-sonnet-5 8 reverse
.\claude-copilot.cmd -p "Read some file and list what is in it. Do not change anything." --allowedTools Read
```

The bridge log, `logs/bridge-<date>-<time>-<port>.log`, says which path each request took. `fresh` is a new conversation, `resume` is tool results going back into a parked turn, and `continue` is a new user message on a live session. `continue-dropped-last` is the same, after Claude Code sent a request of its own that it did not keep (it does that three minutes after a turn); the model is told to disregard that exchange. `fresh-flattened` in the middle of a session means it fell back to the lossy path.

### Clean-machine test in Windows Sandbox

`tests/sandbox/` tests `install-windows.bat` on a Windows with nothing on it. Windows Sandbox has to be enabled first: as admin, then reboot.

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM -All
```

Then:

```powershell
.\tests\sandbox\make-wsb.ps1
```

It writes `logs/cuckoos-nest.wsb` with your repo path and opens it. The repo is mapped read-only and copied to `C:\cuckoos-nest` at logon, so the sandbox never writes into your checkout. `logs/sandbox-out` is mapped writable as `C:\out`, because the Sandbox clipboard comes and goes. Inside the sandbox:

1. Run `C:\cuckoos-nest\install-windows.bat`. It should stop with "winget not found", because Sandbox ships without winget.
2. Run `C:\tests\bootstrap-winget.cmd`. Microsoft's documented way to get winget into Sandbox.
3. Open a new terminal and run `install-windows.bat` again. It should install everything without asking for a new window, then offer `copilot login`.
4. Open another new terminal and run `C:\cuckoos-nest\claude-copilot.cmd`.

## License

MIT.
