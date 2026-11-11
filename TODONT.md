# TODONT

What was tried and did not work, with the numbers. Read before changing the
structure.

## Copilot SDK `mode="empty"`

`CopilotClient(mode="empty")` raises `ValueError: ... requires base_directory,
session_fs, or a UriRuntimeConnection` [OBSERVED 2026-11-09, SDK 1.0.8]. A
separate base directory moves auth away from `~/.copilot`. Default mode with
`available_tools=ToolSet().add_custom("*")`, `system_message` mode `replace`,
`skip_custom_instructions=True` and `enable_skills=False` gives the same
isolation: the first probe call was 549 input tokens.

## Answering parked tool calls in any order

On gpt-6-luna, answering two parked calls in reverse of the model's
`tool_requests` order swapped the results 3 of 3 times; in the model's order
it was correct 3 of 3. gpt-6-sol: swapped 3 of 3. claude-sonnet-5: correct in
reverse order, 3 of 3 [OBSERVED 2026-11-09, CLI 1.0.73]. Answer in the
model's order, sequentially. GPT stays refused anyway, because nothing tells
you when a pairing went wrong.

On CLI 1.0.108 (SDK 1.0.30) no reverse-order run swapped: gpt-6-luna 12 of
13 correct, gpt-6-sol 13 of 13 [OBSERVED 2026-11-10]. The same day CLI
1.0.73 still swapped gpt-6-luna 2 of 2. Keep answering in the model's
order anyway: it costs nothing, and the next CLI may break it again.

## Calling it a Copilot defect without checking the pin

The swap was measured on SDK 1.0.8, which bundles CLI 1.0.73. 1.0.30
(CLI 1.0.108) was already on PyPI. Every document here then said "the
Copilot runtime pairs GPT results by answer order", with no version on it,
and an upstream issue was about to be drafted before anyone looked at the
latest release [OBSERVED 2026-11-10]. A few runs on 1.0.30 showed no swap.
Before blaming a dependency for a defect, or reporting it, rerun on its
latest release. And a claim about someone else's runtime carries the
version it was measured on.

## A fixed sleep before answering in the probe

`probe_tool_order.py` sleeps `delay_s` (8 in the weekly check), then
answers whatever calls are pending. kimi-k3 had made no tool call after
8 s in 1 of 10 runs [OBSERVED 2026-11-10, CLI 1.0.108]; on 2026-11-09 two
of its runs did not have both calls. The probe then answers nothing, waits
180 s and reports FAIL, and the model's verdict is `inconclusive` although
nothing was learned about pairing. It also printed `MAPPING: ok` for a run
that had reordered nothing.

Six more runs with the old probe caught it: five had both calls at 3.4 to
4.2 s, the sixth at 8.8 s, 0.8 s after the probe had looked [OBSERVED
2026-11-10]. The probe now waits up to 60 s for the calls, then holds the
park for `delay_s`, and a run with fewer than two calls says
`MAPPING: untested` and ends at once. kimi-k3 after that: 10 of 10
correct. A verdict of `inconclusive` is a question about the probe first.

## `fixed` as the verdict for "every run correct"

The first mail said claude-sonnet-5 went from (none) to `fixed`. It was
never broken. The verdict is `ok` now, and a repair reads as broken -> ok
in the mail's Was/Now columns. The mail also lists each run and says what
`inconclusive` covers; the first one did neither.

## Living inside agentry

The bridge started as a branch of agentry. Agentry's `Backend` contract is
one user message in, text out, on a LAN-bound always-on server. This needs
tool calls both ways, loopback only, one process per session. It never fit
the interface and moved out.

## A `param()` block in the launcher

`-Port` swallowed claude's `-p` (PowerShell binds any unique prefix). After
renaming to `-Bridge*`, `[CmdletBinding()]`/`[Parameter()]` brought the
common parameters, and `-p` failed as ambiguous with `-ProgressAction` and
`-PipelineVariable` [OBSERVED 2026-11-09, pwsh 7]. `$args` is parsed by hand.

## `Set-Location $PSScriptRoot` in the launcher

Claude Code then works in the bridge's directory, not the caller's project,
and the location change sticks to the caller's PowerShell session.

## One shared bridge for all sessions

Left running between sessions, a shared bridge cannot be torn down without
killing it under another session. Each session now gets its own bridge on
the first free port from 8790.

## `Stop-Process` on the started process

The venv's `python.exe` on Windows is a launcher stub; the interpreter is its
child. Killing the stub left a bridge listening on 8790 [OBSERVED
2026-11-09]. Use `taskkill /PID <pid> /T /F`.

## Free-port check alone

Two sessions started one second apart both picked 8790: the second checked
before the first bridge had bound. The second bridge died on the busy port
and its session used the first one's bridge. A pid file now reserves the
port from launch, and an answer only counts while our own process is alive.

## `claude --allowedTools a b "prompt"`

`--allowedTools` is variadic and eats the trailing prompt ("Input must be
provided either through stdin or as a prompt argument") [OBSERVED
2026-11-09, Claude Code 2.1.319]. Comma-separate the tools and pass the
prompt on stdin or before the flag.

## Finding winget installs only where I expected them

In a clean Windows Sandbox, `winget install --id Microsoft.PowerShell`
(7.6.9.0) installed the MSIX package: no `%ProgramFiles%\PowerShell\7`,
only a 0-byte app execution alias in `%LOCALAPPDATA%\Microsoft\WindowsApps`.
The installer looked only in Program Files and asked for a new window.
`winget install --id GitHub.Copilot` put `copilot.exe` in
`%LOCALAPPDATA%\GitHubCopilotCLI`, not `WinGet\Links`; the installer did not
find it, skipped the login prompt without a word, and the first
`claude-copilot.cmd` died with "JSON-RPC Error -32603: ... Not
authenticated" [OBSERVED 2026-11-09]. Both paths are checked now, and a
Copilot CLI that is installed but not found prints a `[!]` line instead of
nothing. Where winget puts a package is per package and can change; check
after the install, never assume.

## Matching a conversation on model, tool list and exact history

`find_conversation` required the same model, the same tool names and
byte-identical earlier messages. Three things Claude Code does in normal use
broke that, and every miss went to the lossy path [OBSERVED 2026-11-10,
Claude Code 2.1.321]:

- `/model` changes the model (a new Copilot session was made).
- After `/model`, Claude Code re-wrapped the environment block it had
  already sent (message 1, role system) in `<system-reminder>` tags. Same
  content, different text, so message 0's signature changed.
- ToolSearch loading WebSearch grew the tool list from 15 to 16.

In the Fable session the result was a new flattened session on every request
after the first miss: 13, 16, 19 messages, cache_read stuck at 13 961 (the
system prompt) instead of ~29 000. Now: model via `set_model`, tools via
`resume_session`, and user-text changes are tolerated when roles, tool ids
and assistant text match.

## Taking every request on the main history as the conversation

Three minutes after a turn ends, Claude Code sends a request of its own on
the main history (14:21:54 and 15:02:40 in one TUI hour, 78 output tokens
each). It is the away recap: "The user stepped away and is coming back.
Recap in under 40 words" [OBSERVED 2026-11-11, dump]. The bridge matched it as `continue`
and moved the conversation's history past it. Claude Code does not keep
that exchange, so the owner's next message matched nothing and went
`fresh-flattened`: 2 of 14 requests, the first one a 51,166-token cache
write on Opus [OBSERVED 2026-11-10, SDK 1.0.30, Claude Code 2.1.322]. The
second also swallowed a `/model` switch.

Not done: giving the side request its own session. It needs the whole
history, so that is a full cache write every idle pause. Not done either:
guessing which requests are side requests from their text.

Now the conversation remembers its history from before the last `continue`.
A request that shows that history again resumes the same session
(`continue-dropped-last`), and the message is sent with a note telling the
model to disregard the exchange before it. The way back closes when tool
results arrive, because then Claude Code kept the turn.

## Falling back to the default model for unknown ids

`pick_model` used the default for anything it could not map. With Fable 5.1
picked, Claude Code's status line said Fable while claude-opus-5.5 answered,
and only a WARNING in the bridge log said so [OBSERVED 2026-11-10]. Now a 400.

## Passing server tools through as plain tools

Claude Code's WebSearch sends `web_search_20250305`, which Anthropic runs
server side. As a declared tool with no handler, the model answered without
searching and Claude Code showed "Did 0 searches", no error [OBSERVED
2026-11-10]. Now a 400 naming the tool.

## Auto mode with the server-side check

By default Claude Code (2.1.278+) asks the server for the auto mode verdict
inside the model requests when `ANTHROPIC_BASE_URL` points at a gateway.
Nothing answers that through the bridge, and actions it would judge are
refused without a prompt [OBSERVED 2026-11-10]. Do not answer the check from
the bridge: that would be faking a safety mechanism.

First fix, wrong: force `--permission-mode acceptEdits` and call auto mode
impossible. `CLAUDE_CODE_AUTO_MODE_SERVER=0` makes Claude Code send its own
classifier requests, which the bridge serves like any call [DOCUMENTED
code.claude.com/docs/en/permission-modes; OBSERVED 2026-11-10]. The launcher
sets it.

The classifier's stage 1 asks for `<severity>N</severity>` with stop sequence
`</severity>` and max_tokens 64. Copilot has no stop sequences; the bridge
cuts non-streamed replies afterwards. Each check made a Copilot session that
was never closed; tool-less requests now close theirs.

## -BridgeStop on every pid file

It killed every bridge with a pid file, including ones in use. Testing the
stale-pid check, I ran it and killed the owner's idle interactive session on
8790 [OBSERVED 2026-11-10]. The pid file now has the owning PowerShell on
line 2, and -BridgeStop leaves the bridge while that process lives. The pid
on line 1 must also still be `python.exe ... bridge.py --port N`, so a pid
reused after a reboot is never killed.

## Logs named by date and port

The next run on the same port the same day overwrote the log. A test's
evidence was gone before anyone read it [OBSERVED 2026-11-10]. The name now
has the start time.

## Pasting into Windows Sandbox

The clipboard worked out of the sandbox, then died both ways mid-test
[OBSERVED 2026-11-09]. `make-wsb.ps1` now maps `logs\sandbox-out` writable
as `C:\out`; redirect results there instead of copying text.

## Starting the bridge with `Start-Process uv run ...`

The `uv` on PATH was `%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe`, a link
that relaunches the real uv and exits. `Start-Process -PassThru` got the pid
of the process that exited (HasExited was True 3 s after start), and
`taskkill /T` on it missed the real tree: a bridge from an earlier session was
still listening on 8790, and the next session moved to 8791 [OBSERVED
2026-11-09, uv 0.12.17 via winget]. The launcher now runs `uv sync` and starts
`.venv\Scripts\python.exe` itself.
