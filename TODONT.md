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
