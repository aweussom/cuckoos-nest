# STATUS

Claude Code runs on Copilot models through `bridge.py` on `claude-opus-5.5`
and `claude-sonnet-5`, headless and in the interactive TUI. The TUI has had
a few short sessions with tools, not real work. A conversation now stays on
one Copilot session through `/model` and mid-session tool additions.
`install-windows.bat` has been run end to end on a clean Windows Sandbox.
WebSearch cannot work through the bridge. Auto mode works with the
client-side classifier, which the launcher turns on.

The SDK pin is 1.0.30 (CLI 1.0.108) since 2026-11-10; everything dated
before that was measured on 1.0.8 (CLI 1.0.73). The tool-result pairing
defect that kept GPT out is in CLI 1.0.73 and was not seen on 1.0.108.
The allowlist is `claude-` and `gpt-` since 2026-11-10. kimi-k3 measures
ok but is not on the list.

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
- Tool-result pairing, parked calls answered in reverse order:
  - CLI 1.0.73 (SDK 1.0.8): gpt-6-luna and gpt-6-sol swapped 3 of 3
    [OBSERVED 2026-11-09]; gpt-6-luna swapped 2 of 2 again
    [OBSERVED 2026-11-10], minutes after the first runs below. So the fix
    is in the CLI, somewhere after 1.0.73, not on the server side
    [INFERRED]. No changelog line found, no upstream issue found in
    github/copilot-sdk.
  - CLI 1.0.108 (SDK 1.0.30) [OBSERVED 2026-11-10]: gpt-6-luna 12 of 13
    correct, gpt-6-sol 13 of 13, claude-sonnet-5 11 of 11, no swap in any
    run. The odd gpt-6-luna run paired correctly but its final text lacked
    a value.
  - kimi-k3, CLI 1.0.108 [OBSERVED 2026-11-10]: with the old probe (answer
    whatever is pending 8 s after the prompt) 14 of 16 runs correct, and 2
    where it had made no call yet at 8 s. One of those was logged in
    full: both calls came at 8.8 s, in one message; in the other 14 they
    came at 3.4 to 4.2 s where logged. So `inconclusive` was the probe's
    clock, not pairing. With the probe waiting for the calls: 10 of 10
    correct.
  - Last `check_tool_order.py` verdicts [OBSERVED 2026-11-10, CLI 1.0.108]:
    gpt-6-luna ok, gpt-6-sol ok, kimi-k3 ok, claude-sonnet-5 ok (control).
    The verdict for "every run correct" is now `ok`; it was `fixed`, which
    read wrong for a model that was never broken.
- GPT through the bridge after `gpt-` went into the allowlist [OBSERVED
  2026-11-10, gpt-6-luna as main and small model]: one headless
  `claude-copilot.ps1 -p` run with two parallel Reads, Edit and Bash
  answered correctly; log `fresh` then `resume` x4. Claude Code warns that
  it does not know the model and assumes a 200k context window.
- Bridge on SDK 1.0.30 [OBSERVED 2026-11-10, claude-opus-5.5]: one headless
  `claude-copilot.ps1 -p` run with two parallel Reads, Edit and Bash
  answered correctly; log `fresh` then `resume` x3, no pid file left
  afterwards. The private imports (`copilot._mode`,
  `copilot._cli_version`) still resolve. 1.0.30 refuses a relative
  `working_directory`; only the probe passed one.

- Interactive TUI on SDK 1.0.30, one hour, Opus then Sonnet [OBSERVED
  2026-11-10]: 14 requests, 2 of them `fresh-flattened`, no errors. Both
  followed a request Claude Code sent by itself 3 minutes after a turn
  ended (14:21:54 and 15:02:40, 78 output tokens each). The bridge took it
  as `continue`; the owner's next message then had a history the
  conversation did not, and went to a new session (51,166 tokens written
  to the cache again on Opus). The request is Claude Code's away recap:
  the history plus a user message starting "The user stepped away and is
  coming back. Recap in under 40 words" [OBSERVED 2026-11-11, dump,
  Claude Code 2.1.322].
- Fix for that, same day: a request whose history is what a conversation
  had before its last `continue` resumes that conversation, path
  `continue-dropped-last`, and the model is told to disregard the dropped
  exchange. `tests/test_matching.py` (offline, fake conversations) passes.
  Replayed by hand against a live bridge on claude-sonnet-5: main turn,
  side request, next message stayed on one Copilot session, and the model
  did not know the number the side request had given it [OBSERVED
  2026-11-10].
- The same in a real TUI session [OBSERVED 2026-11-11, SDK 1.0.30, Claude
  Code 2.1.322]: a turn with tools on Opus, the away recap 3 minutes
  later (`continue`), then, after `/model` to Sonnet, the owner's next
  message: `continue-dropped-last` on the same conversation, model
  switched by `set_model` on the live session, earlier user text changed
  and tolerated. 10 requests, no `fresh-flattened`. That message wrote
  44,064 tokens to the cache and read none, which is expected: another
  model, and nearly three hours idle. A second recap followed as a plain
  `continue`; nothing was sent after it.

## Not verified

- A message after the away recap without a model switch in between, where
  the cache should be read, not rewritten.
- A one-step rewind of an exchange without tools now takes the same path
  as a side request: the session keeps the rewound exchange and the model
  is told to disregard it. Before, it was flattened. Not tried.
- On SDK 1.0.30: the interactive TUI, subagents, `-c` follow-ups, `/model`
  (`set_model`), mid-session tool additions (`resume_session`), the auto
  mode classifier and a long park. All of them were measured on 1.0.8 only.
- A model set in the user's Claude Code settings beats the
  `ANTHROPIC_MODEL` the launcher sets: with a Fable default there, the
  launcher's claude asked for `claude-fable-5-2` and got the 400.
  `--model claude-opus-5.5` on the command line got past it [OBSERVED
  2026-11-10; the settings default as the cause is the owner's
  explanation, the precedence is INFERRED]. Headless runs cannot `/model`
  their way out, so the launcher may need to pass `--model` itself. Not
  done.
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
  [OBSERVED 2026-11-10]. Also fixed: -BridgeStop checks that the pid is
  still our bridge (a ping process in a fake pid file survived) and leaves
  bridges whose launcher PowerShell is alive; ports are reserved with
  CreateNew when picked. Two sessions started together got 8790 and 8791,
  -BridgeStop mid-run left both, both answered [OBSERVED 2026-11-10].
  Open from that review (REVIEW.md itself deleted once these were moved
  here), all [INFERRED] from reading the code:
  - `find_conversation` does not skip a busy conversation, and
    `plan_request` changes sigs, model and tools before `run_turn` takes
    `conv.busy`. A side request forking the main history is spliced into
    the main session: seen 2026-11-10 and handled after the fact (above),
    for a side request that arrives while the session is idle. One that
    arrives while a turn is running is still open; so is a tool-less one,
    which would `retool([])` the conversation and close it as a one-shot.
    Cheap guard: skip conversations whose `busy` lock is held, and log it.
    The new third-choice match already does.
  - Conversations that end normally keep their Copilot session until the
    bridge exits (one per subagent in a long TUI session).
  - `PARK_TIMEOUT_S = 1800`: a permission prompt left 30 min loses the
    session to the lossy path. Longest measured park is 420 s.
  - Text Claude Code sends beside tool results (reminders, a user
    interjection) is appended to the first tool result, so the model
    cannot tell it from file content. Copilot limit; belongs in README
    Limits, maybe with a marker tag.
  - `pick_model` maps sonnet/opus to hard-coded ids, not `--model` /
    `--small-model` (only bites when run by hand). Its docstring says
    `claude-sonnet-5-5`, unchecked against a dump.
  - `bridge.py` imports private SDK modules (`copilot._mode`,
    `copilot._cli_version`); an SDK upgrade must check them first. Both
    were there in 1.0.30 [OBSERVED 2026-11-10].
  - `count_tokens` is `len(json)//4`; base64 images inflate it.
  - Offline tests worth writing, fixtures from scrubbed dumps:
    `message_signature`, `normalize_messages`, the stop-sequence cut, and
    the resume branch of `plan_request` (tool results clearing the
    way back). `find_conversation` with fake conversations exists:
    `tests/test_matching.py`.

## Next

1. Owner: decide whether `kimi-` goes into `VERIFIED_MODEL_PREFIXES`. The
   gate in CLAUDE.md (a `check_tool_order.py` verdict of `ok`) is met on
   CLI 1.0.108. Nothing has been run on kimi-k3 through the bridge.
2. Owner: an hour of interactive work through `claude-copilot.ps1`, now on
   SDK 1.0.30.
3. Reuse the task suite from cloud-and-local-coding-harness (fix, feature,
   delegate, hunt, rename) for numbers against the direct Anthropic path.
4. Register `check_tool_order.py` as a weekly scheduled task. It also
   catches the defect coming back in a later CLI.
