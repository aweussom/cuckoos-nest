# TODO

Next steps, in order. What is true today is in `STATUS.md`; what failed is
in `TODONT.md`.

1. An hour of real interactive work through `claude-copilot.ps1`. Watch the
   bridge log for `fresh-flattened` and `resuming although`, and note the
   AI credits used.
2. Work through "Open from that review" in `STATUS.md`. The cheapest first:
   skip busy conversations in `find_conversation`.
3. The "API Usage Billing" banner. Claude Code's header says
   `Opus 5.5 with medium effort · API Usage Billing` because an auth token
   is set. Users will read that as paying Anthropic; it is Copilot credits.
   Find out whether any setting or env var changes that text [GUESS: none].
   If not, say it in README, near the top.
4. Blog post, then dev.to. Say plainly that GitHub's terms neither allow
   nor forbid this; OpenCode has a formal partnership, this has none.
   Screenshots: TUI mid-session with a tool call, the bridge log with
   fresh/resume/continue, the installer in Windows Sandbox. Crop the
   Copilot login name.

5. claude-sonnet-5 is gone from Copilot [OBSERVED 2026-11-25; offered:
   claude-haiku-5.5, claude-opus-5.5, claude-sonnet-5.5, gpt-5.3-codex,
   gpt-6-luna, gpt-6.1-terra, gpt-6.2-astra, gpt-6.2-sol, kimi-k3]. The
   launcher and bridge defaults moved to claude-sonnet-5.5. Still on the old
   name: CONTROL in check_tool_order.py (the check fails until it changes, and
   claude-sonnet-5.5 needs its own pairing run first), the probe line in
   CLAUDE.md, README examples and price table.
