# Coding-harness backend feasibility (2026-11-09)

Question: can a coding harness (Claude Code preferred, opencode acceptable)
run on GitHub Copilot models?

Answer: yes for Claude Code, through the official Copilot SDK, with no raw
API access. Prototype: `bridge.py`; probe: `probe_tool_order.py`.

Written while the code lived on a feasibility branch of agentry
(github.com/aweussom/agentry); it moved here the same day. File names below
are the ones in this repo.

Versions [OBSERVED 2026-11-09]: github-copilot-sdk 1.0.8, Claude Code 2.1.319.

## Mechanism

The Copilot SDK gives an agent session, not completions. Three session
options turn it into something close enough to a model endpoint:

- `system_message={"mode": "replace", ...}`: Claude Code's system prompt
  replaces Copilot's. First probe call was 549 input tokens [OBSERVED].
- `available_tools=ToolSet().add_custom("*")`: only client-declared tools,
  no Copilot built-ins.
- `Tool(..., handler=None)`: a declared tool with no handler. The runtime
  emits `external_tool.requested` and parks the turn until
  `session.rpc.tools.handle_pending_tool_call(request_id, result)` answers.

The bridge returns the parked calls to Claude Code as `tool_use` with
`stop_reason: tool_use`. The next `/v1/messages` call carries the
`tool_result` blocks, which are fed back into the parked turn.

`mode="empty"` was not used: it requires a separate `base_directory`, which
would move auth away from `~/.copilot` [OBSERVED: ValueError on construct].

## What was tested [OBSERVED 2026-11-09]

| Test | Model | Result | Wall |
|---|---|---|---|
| Fix a failing unit test (Bash, Read x2 parallel, Edit, Bash) | gpt-6-luna | pass, correct diff | 14 s |
| Add `median()` with tests | claude-opus-5.5 | pass, 5 tests | 16 s |
| Follow-up via `claude -c` | claude-opus-5.5 | pass, 6 tests, same Copilot session | 10 s |
| Agent tool, one subagent | opus main, sonnet sub | pass | 14 s |
| Agent tool, background subagent + completion notice | luna main, sonnet sub | pass | 8 s |
| Turn parked 420 s before tool results | gpt-6-luna | pass, turn resumed | |

Every step of a conversation resumed the same Copilot session. Prompt cache
hit almost the whole context from the second call on (e.g. in=19280,
cache_read=18857).

All runs were `claude -p --setting-sources project`. The interactive TUI was
not driven.

## Defect found: GPT result pairing is order-based

On gpt-6-luna, answering two parked calls in reverse of the model's
`tool_requests` order swapped the results, 3 of 3 runs. Answering in the
model's order was correct 3 of 3. claude-sonnet-5 was correct in reverse
order, 2 of 2. So the runtime pairs GPT tool results by answer order, not
by request id [OBSERVED]. The bridge answers sequentially in the model's
order; the loop in `plan_request` carries a comment saying why.

Worth an upstream report to github/copilot-sdk after a minimal repro.

Policy since then: the bridge refuses every model outside
`VERIFIED_MODEL_PREFIXES` (today `claude-`), at startup and per request.
`BRIDGE_ALLOW_UNVERIFIED=1` lifts it. `check_tool_order.py` reruns
the reverse-order probe 5 times per model and mails through PaMail when a
verdict changes. First runs [OBSERVED 2026-11-09, CLI 1.0.73]:

| Model | Verdict | Runs |
|---|---|---|
| gpt-6-luna | broken | 3 of 3 swapped |
| gpt-6-sol | broken | 3 of 3 swapped |
| kimi-k3 | inconclusive | 6 of 6 usable runs correct, 2 runs without both tool calls |
| claude-sonnet-5 | fixed (control) | 3 of 3 correct |

## Things Claude Code sends that a plain proxy would choke on

- `role: "system"` messages inside `messages`, also as the last message
  (environment block). The bridge folds them into the user turn as
  `<system-message>` text.
- Subagents ask for `claude-sonnet-5-5` whatever `ANTHROPIC_MODEL` says.
  Mapped by family to Copilot's `claude-sonnet-5` / `claude-opus-5.5`.
- `--allowedTools` is variadic and eats a trailing prompt argument. Pass
  the prompt on stdin.

## Cost [INFERRED from logged tokens x models.list prices]

Prices are AI credits per 1M tokens (1 credit = 1 cent):

| Model | Input | Output | Cache read | Cache write |
|---|---|---|---|---|
| claude-opus-5.5 | 400 | 2000 | 20 | 500 |
| claude-sonnet-5 | 200 | 1000 | 20 | 250 |
| gpt-6-sol | 200 | 1000 | 20 | 250 |
| gpt-6-luna | 10 | 50 | 1 | 12 |

The two Opus tasks above came to roughly 17 credits. The first call of a
session pays cache write on the full ~19k-token Claude Code prompt; later
calls mostly pay cache reads. Not checked against the Copilot usage ledger.

## Not done, known gaps

- Interactive TUI, Esc/cancel mid-stream, `/compact`, rewind. Cancel closes
  the session; the next call then takes the lossy path below.
- Lossy path: a call that matches no live conversation gets a fresh session
  with earlier history flattened to text. Hit by compaction, rewind, bridge
  restart. Quality on that path is untested.
- Tool-set changes mid-conversation (MCP servers connecting, deferred tools)
  start a new session through the lossy path.
- Thinking blocks are not emitted; reasoning effort is not forwarded.
- Images in tool results are passed as `binary_results_for_llm`; untested.
- `count_tokens` is a len/4 estimate.
- Parked sessions are reaped after 30 min; the runtime's own limit on a
  parked turn is above 420 s and otherwise unknown.
- Single global Copilot client, no auth on the endpoint. Loopback bind is
  enforced (`--host` refuses anything else): this endpoint hands out tool
  calls that the harness executes locally.
- opencode does not need this bridge for Copilot: GitHub supports Copilot
  login in opencode officially since 2026-01 (`opencode auth login`). The
  bridge would only matter for backends without such a login, behind
  `/v1/chat/completions` with `tools`/`tool_calls`.
- Copilot terms for powering a third-party harness through the SDK were not
  checked. This uses the documented SDK surface only, no private endpoints.

## Running it

`claude-copilot.ps1` does all of this per session. By hand:

```bash
uv run bridge.py --port 8790 --model claude-opus-5.5 --small-model claude-sonnet-5
```

```bash
ANTHROPIC_BASE_URL=http://127.0.0.1:8790 ANTHROPIC_AUTH_TOKEN=x ANTHROPIC_API_KEY= \
ANTHROPIC_MODEL=claude-opus-5.5 ANTHROPIC_DEFAULT_HAIKU_MODEL=claude-sonnet-5 \
CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 claude
```

`BRIDGE_DUMP_DIR=<dir>` writes every request body as JSON. Those files
contain prompts and file contents.
