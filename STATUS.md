# STATUS

Claude Code runs on Copilot models through `bridge.py` on `claude-opus-5.5`
and `claude-sonnet-5`, headless and in the interactive TUI. The TUI has had
one short session with a tool call, not real work. `install-windows.bat`
has been run end to end on a clean Windows Sandbox. GPT models are refused
because of a Copilot runtime defect in tool-result pairing.

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
- `check_tool_order.py`, first run [OBSERVED 2026-11-09, CLI 1.0.73]:
  gpt-6-luna broken, gpt-6-sol broken, kimi-k3 inconclusive, claude-sonnet-5
  fixed (control).

## Not verified

- Interactive TUI on real work, Esc mid-turn, `/compact`, rewind. All of
  them except the TUI itself go through the lossy path (history flattened
  to text).
- The `[!]` message when the Copilot CLI is installed but not found; it is
  the fallback, and the second sandbox found copilot.
- Images in tool results.
- Whether Copilot's terms cover driving another vendor's harness through the
  SDK.
- Behaviour with a full user setup: hooks, skills and MCP servers from
  `~/.claude`. Headless tests ran with `--setting-sources project`.

## Next

1. Owner: an hour of interactive work through `claude-copilot.ps1`.
2. Reuse the task suite from cloud-and-local-coding-harness (fix, feature,
   delegate, hunt, rename) for numbers against the direct Anthropic path.
3. Register `check_tool_order.py` as a weekly scheduled task.
