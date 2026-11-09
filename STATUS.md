# STATUS

Claude Code runs on Copilot models through `bridge.py`, headless, on
`claude-opus-5.5` and `claude-sonnet-5`. The interactive TUI has not been
driven yet; that is the next test, and it needs the owner. GPT models are
refused because of a Copilot runtime defect in tool-result pairing.

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
- `claude-copilot.ps1`: two concurrent sessions got ports 8790 and 8791;
  both bridges were gone afterwards, no pid files left [OBSERVED 2026-11-09].
  After the move to `uv run`: one headless run with a Read call, Copilot
  session resumed, bridge and pid file gone afterwards; one reverse-order
  probe on claude-sonnet-5 correct [OBSERVED 2026-11-09, uv 0.12.17].
  The two-session test has not been repeated under uv.
- `check_tool_order.py`, first run [OBSERVED 2026-11-09, CLI 1.0.73]:
  gpt-6-luna broken, gpt-6-sol broken, kimi-k3 inconclusive, claude-sonnet-5
  fixed (control).

## Not verified

- Interactive TUI, Esc mid-turn, `/compact`, rewind. All of them except the
  TUI itself go through the lossy path (history flattened to text).
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
