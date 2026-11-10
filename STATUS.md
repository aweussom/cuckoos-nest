# STATUS

Claude Code runs on Copilot models through `bridge.py` on `claude-opus-5.5`
and `claude-sonnet-5`, headless and in the interactive TUI. The TUI has had
a few short sessions with tools, not real work. A conversation now stays on
one Copilot session through `/model` and mid-session tool additions.
`install-windows.bat` has been run end to end on a clean Windows Sandbox.
GPT models are refused because of a Copilot runtime defect in tool-result
pairing. WebSearch cannot work through the bridge. Auto mode works with
the client-side classifier, which the launcher turns on.

## Verified

- 2026-11-09, SDK 1.0.8, Claude Code 2.1.319, headless (`-p`):
  bug fix with Bash, parallel Read and Edit (gpt-6-luna, before GPT was
  refused); new function with tests and a `-c` follow-up on the same Copilot
  session (claude-opus-5.5); foreground and background subagents mapped to
  claude-sonnet-5. All passed [OBSERVED 2026-11-09].
- A turn parked 420 s before tool results resumed normally [OBSERVED
  2026-11-09, gpt-6-luna].
- Prompt cache: from the second call of a conversation, nearly the whole
  context is a cache read [OBSERVED 2026-11-09].
- `claude-copilot.ps1` (uv sync, then `.venv\Scripts\python.exe` directly):
  one headless run with a Read call through `claude-copilot.cmd`, Copilot
  session resumed, no bridge process and no pid file afterwards; two
  concurrent sessions got ports 8790 and 8791, both torn down [OBSERVED
  2026-11-09, uv 0.12.17]. One reverse-order probe on claude-sonnet-5 via
  `uv run` correct.
- `install-windows.bat` on a machine that already had everything: all four
  tools found, `uv sync` done, login prompt declined, exit 0. From a
  116-character path it refused with exit 1 [OBSERVED 2026-11-09].
- `install-windows.bat` on a clean Windows Sandbox, two sandboxes
  [OBSERVED 2026-11-09]:
  - Without winget it stops with the "winget not found" text and the two
    options. Exit code not read; that branch ends in `exit /b 1`
    [INFERRED].
  - After `tests\sandbox\bootstrap-winget.cmd`: winget installed
    PowerShell 7.6.9.0, uv 0.13.7 (with VC++ redist), Claude Code 2.1.317
    and the Copilot CLI; `uv sync` pulled CPython 3.15.
  - First sandbox found two bugs, both fixed and re-run in the second:
    winget chose the MSIX PowerShell (only a 0-byte alias in
    `%LOCALAPPDATA%\Microsoft\WindowsApps`), so the installer asked for a
    new window; and `copilot.exe` landed in
    `%LOCALAPPDATA%\GitHubCopilotCLI`, so the login step was skipped
    without a word and the bridge then failed with "Not authenticated".
    Second sandbox: no new window after pwsh, login prompt shown,
    `copilot login` through the full path signed in, and in a new terminal
    an interactive TUI turn with a search tool answered correctly.
  - First sandbox, after a manual `copilot login`, new terminal:
    `claude-copilot.cmd -p "Reply READY"` answered
    READY, log `fresh`, bridge stopped afterwards. One interactive TUI turn
    ("read README.md and give me the first heading") used a search tool and
    answered correctly.
  - uv: the installer continued through `WinGet\Links\uv.exe` without a new
    window. Claude Code needs a new terminal after install, as the installer
    says.
- Session continuity, interactive TUI, Claude Code 2.1.321, SDK 1.0.8
  [OBSERVED 2026-11-10]: one session (`conv_fbfae5efdf`) went fresh ->
  resume -> `/model` Opus to Sonnet (`set_model`, history kept) -> continue
  x3 -> WebSearch loaded by ToolSearch (`resume_session` with 16 tools) ->
  resume. No `fresh-flattened`. Before the fix, the same events flattened
  every later request.
- `resume_session` on a live session id with a larger tool list keeps
  history and the new tool is callable, also while a turn is parked; no
  duplicate events. `set_model` keeps history. Scratch probes, a few
  credits [OBSERVED 2026-11-10, claude-sonnet-5].
- Unknown model (`claude-fable-5-1`) gets a 400 naming the usable models;
  `web_search_20250305` gets a 400 and the model reports it [OBSERVED
  2026-11-10].
- Auto mode, server-side check (the default with a gateway): never answers
  through the bridge, Bash calls it would judge are refused without a
  prompt; one denial did not break the session [OBSERVED 2026-11-10].
- Auto mode, client-side classifier (`CLAUDE_CODE_AUTO_MODE_SERVER=0`, set
  by the launcher), headless [OBSERVED 2026-11-10]: one stage-1 classifier
  call per checked Bash call, to claude-sonnet-5, cut at `</severity>`,
  session closed after. Allowed: curl to example.com, POST of README to
  httpbin, push to a temp branch. Force push stopped by a deny rule in the
  owner's settings, not the classifier. A push-delete blocked on Anthropic's
  API was allowed through the bridge, but that prompt asked for it outright.
  The classifier blocking something itself through the bridge: not seen.
- Classifier cost: its system prompt is ~47,800 tokens. Fresh session cold:
  47,807 cache write; second run: 47,718 cache read, 89 write [OBSERVED
  2026-11-10, probe]. Roughly 12 credits cold, 1 warm, on Sonnet 5.
- Usage numbers the bridge reports for fast one-shot calls are wrong
  (classifier showed cache_write ~4,200, probe showed 47,807): the usage
  event seems to arrive after idle [INFERRED]. Display only; Copilot bills
  what it counts.
- `ENABLE_CLAUDEAI_MCP_SERVERS=false` silences the claude.ai connectors
  warning; `--strict-mcp-config` does not [OBSERVED 2026-11-10, 2.1.321].
- Copilot bills per token in AI credits ($0.01); Opus 5.5 $4 in / $0.20
  cached / $5 cache write / $20 out per 1M, Sonnet 5 $2 / $0.20 / $2.50 /
  $10 [DOCUMENTED docs.github.com models-and-pricing, read 2026-11-10].
- `check_tool_order.py`, first run [OBSERVED 2026-11-09, CLI 1.0.73]:
  gpt-6-luna broken, gpt-6-sol broken, kimi-k3 inconclusive, claude-sonnet-5
  fixed (control).

## Not verified

- Interactive TUI on real work, Esc mid-turn, `/compact`, rewind. All of
  them except the TUI itself go through the lossy path (history flattened
  to text).
- The loose history match (earlier user text changed, structure the same)
  could in theory resume the wrong conversation; it requires identical
  roles, tool ids and assistant text, so I think that is unlikely
  [INFERRED]. Watch for `resuming although` in the log.
- System prompt changes mid-session still flatten. Not seen yet.
- The `[!]` message when the Copilot CLI is installed but not found; it is
  the fallback, and the second sandbox found copilot.
- Images in tool results.
- Whether Copilot's terms cover driving another vendor's harness through the
  SDK.
- Actual MCP tool calls. The interactive sessions ran with the owner's full
  `~/.claude` (global CLAUDE.md, skills, deferred MCP tools); no MCP tool
  was called. Hooks fire: the owner's tab-colour hook works, but its
  UserPromptSubmit run timed out at 5 s twice [OBSERVED 2026-11-10], cause
  unknown.
- REVIEW.md (2026-11-10, read-only review from a bridge session) lists
  open findings. Fixed: no auth (per-run token, 401 without it) and the
  half-sent response when start() fails (now `[bridge error]` and a closed
  conversation; offline test with a raising start(), stream and JSON)
  [OBSERVED 2026-11-10]. Open: -BridgeStop and pid reuse, port
  reservation gap, side requests matching the main conversation.

## Next

1. Owner: an hour of interactive work through `claude-copilot.ps1`.
2. Reuse the task suite from cloud-and-local-coding-harness (fix, feature,
   delegate, hunt, rename) for numbers against the direct Anthropic path.
3. Register `check_tool_order.py` as a weekly scheduled task.
