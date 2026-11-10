#requires -Version 7.0
# Run Claude Code on GitHub Copilot models through bridge.py.
# Background and measurements: docs/FEASIBILITY-2026-11-09.md.
#
#   .\claude-copilot.ps1                        # interactive claude on claude-opus-5.5
#   .\claude-copilot.ps1 -BridgeModel claude-sonnet-5
#   .\claude-copilot.ps1 -c                     # everything else goes to claude as-is
#   .\claude-copilot.ps1 -p "fix the tests"
#   .\claude-copilot.ps1 -BridgeStop            # kill bridges orphaned by a closed window
#
# Every run starts its own bridge on the first free port from 8790 and tears
# it down when claude exits, so two sessions never share or kill each other's
# bridge, and nothing is left running. Loopback only.
# Log: logs/bridge-<date>-<time>-<port>.log in this directory.
#
# Needs: uv (it creates and syncs .venv from uv.lock on first run), Claude
# Code on PATH, and Copilot logged in for this Windows user (`copilot login`,
# or any Copilot CLI/SDK login on this machine).
# Spends Copilot AI credits, not Claude subscription quota. Only claude-*
# models: the bridge refuses GPT (tool-result pairing defect, see the note).

# No param() block on purpose. PowerShell binds any unique prefix of a
# parameter name, and a param block with attributes also brings the common
# parameters (-ProgressAction, -Verbose, -Debug, ...). Either way claude's
# short flags (-p, -c, -d, -v) get eaten. So $args is parsed by hand: the
# -Bridge* flags are ours, everything else goes to claude untouched.
$BridgePort = 8790
$BridgeModel = "claude-opus-5.5"
$BridgeSmallModel = "claude-sonnet-5"
$BridgeStop = $false
$ClaudeArgs = @()
$i = 0
while ($i -lt $args.Count) {
    $a = [string]$args[$i]
    if ($a -ieq '-BridgePort') {
        $BridgePort = [int]$args[$i + 1]
        $i += 2
        continue
    }
    if ($a -ieq '-BridgeModel') {
        $BridgeModel = [string]$args[$i + 1]
        $i += 2
        continue
    }
    if ($a -ieq '-BridgeSmallModel') {
        $BridgeSmallModel = [string]$args[$i + 1]
        $i += 2
        continue
    }
    if ($a -ieq '-BridgeStop') {
        $BridgeStop = $true
        $i += 1
        continue
    }
    $ClaudeArgs += $a
    $i += 1
}

$ErrorActionPreference = 'Stop'
# No Set-Location: claude must run in the caller's project directory, and a
# location change in a script sticks to the caller's session. Absolute paths.

$logDir = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Force $logDir | Out-Null

# Who holds the pid file for $Port? Pids are reused: after a reboot a stale
# file can point at anything, and taskkill /T /F on it would kill an
# unrelated process tree (REVIEW.md). A pid file holds our bridge
# (python.exe ... bridge.py --port N) or, while a session starts, the
# PowerShell that reserved the port. That may be the user's own shell, so a
# 'launcher' holder is never killed, only respected.
# Returns 'bridge', 'launcher' or 'stale'.
function Get-PidFileHolder([int]$ProcessId, [int]$Port) {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $p) {
        return 'stale'
    }
    $cmd = [string]$p.CommandLine
    if ($cmd -like "*bridge.py*--port $Port*") {
        return 'bridge'
    }
    if ($p.Name -in @('pwsh.exe', 'powershell.exe')) {
        return 'launcher'
    }
    return 'stale'
}

if ($BridgeStop) {
    # Normal runs clean up after themselves. A pid file left behind means a
    # session ended without reaching its cleanup (window closed, killed).
    $pidFiles = @(Get-ChildItem -Path $logDir -Filter 'bridge-*.pid' -ErrorAction SilentlyContinue)
    if ($pidFiles.Count -eq 0) {
        Write-Host "No orphaned harness bridges (no pid files in $logDir)."
        exit 0
    }
    foreach ($f in $pidFiles) {
        # Line 1: the pid holding the port (bridge, or the launcher while it
        # starts). Line 2, once the bridge runs: the PowerShell that owns it.
        $lines = @(Get-Content $f.FullName)
        $orphanPid = [int]$lines[0]
        $orphanPort = [int]($f.BaseName -replace '^bridge-', '')
        if ($lines.Count -ge 2) {
            $ownerPid = [int]$lines[1]
            $owner = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
            if ($null -ne $owner -and $owner.ProcessName -in @('pwsh', 'powershell')) {
                # Its session may be idle, not dead (killed one by mistake
                # on 2026-11-10). That launcher stops the bridge itself.
                Write-Host "Leaving $($f.Name): its session (PowerShell pid $ownerPid) is still running"
                continue
            }
        }
        $holder = Get-PidFileHolder $orphanPid $orphanPort
        if ($holder -eq 'launcher') {
            Write-Host "Leaving $($f.Name): pid $orphanPid is a PowerShell holding the port while a session starts"
            continue
        }
        if ($holder -eq 'stale') {
            Write-Host "Not killing pid $orphanPid ($($f.Name)): gone, or not our bridge any more. Removing the stale pid file."
            Remove-Item $f.FullName
            continue
        }
        Write-Host "Stopping orphaned harness bridge pid $orphanPid and its children ($($f.Name))"
        # /T: the venv python.exe is a launcher stub; the bridge is its child.
        & taskkill.exe /PID $orphanPid /T /F 2>&1 | Out-Null
        Remove-Item $f.FullName
    }
    exit 0
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv not on PATH. Install it: winget install astral-sh.uv   (or see https://docs.astral.sh/uv/)"
    exit 1
}
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Error "claude not on PATH. Install Claude Code first."
    exit 1
}

# First free loopback port from $BridgePort. Another session's bridge, or
# anything else, keeps its port.
$port = $null
for ($candidate = $BridgePort; $candidate -lt $BridgePort + 20; $candidate++) {
    $candidatePidFile = Join-Path $logDir "bridge-$candidate.pid"
    # A pid file whose process is gone or is not ours is left over from a
    # session that never cleaned up. It must not block the port forever.
    if (Test-Path $candidatePidFile) {
        $holderPid = [int]@(Get-Content $candidatePidFile)[0]
        $holder = Get-PidFileHolder $holderPid $candidate
        if ($holder -ne 'stale') {
            continue
        }
        Write-Host "Removing stale $candidatePidFile (pid $holderPid is gone or not ours)"
        Remove-Item $candidatePidFile -ErrorAction SilentlyContinue
    }
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $candidate)
    try {
        $listener.Start()
        $listener.Stop()
    } catch {
        continue
    }
    # Reserve the port now, not after uv sync: two sessions started close
    # together both saw it free (REVIEW.md). CreateNew fails if the other
    # one wrote first, so only one of them gets it. Holds our pid until the
    # bridge's replaces it.
    try {
        $fs = [System.IO.File]::Open($candidatePidFile, [System.IO.FileMode]::CreateNew)
        $bytes = [System.Text.Encoding]::ASCII.GetBytes([string]$PID)
        $fs.Write($bytes, 0, $bytes.Length)
        $fs.Close()
    } catch {
        Write-Host "Port $candidate was just reserved by another session; trying the next"
        continue
    }
    $port = $candidate
    break
}
if ($null -eq $port) {
    Write-Error "No free port in $BridgePort..$($BridgePort + 19). Orphaned bridges? Try -BridgeStop."
    exit 1
}

$baseUrl = "http://127.0.0.1:$port"
$pidFile = Join-Path $logDir "bridge-$port.pid"
# Time in the name: one log per run. With only date and port, the next run on
# the same port overwrote the previous log (lost a test, 2026-11-10).
$log = Join-Path $logDir ("bridge-{0:yyyy-MM-dd-HHmmss}-{1}.log" -f (Get-Date), $port)

Write-Host "Syncing Python environment (uv sync --frozen); the first run downloads dependencies"
& uv sync --frozen --quiet --project $PSScriptRoot
if ($LASTEXITCODE -ne 0) {
    # Release the port first: Write-Error stops the script here.
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    Write-Error "uv sync failed (exit $LASTEXITCODE) in $PSScriptRoot"
    exit 1
}

# Start the venv's python directly, not `uv run`. The `uv` on PATH may be a
# winget link that relaunches the real uv and exits at once: Start-Process
# then returns a pid that is already gone, and teardown misses the bridge
# (TODONT.md). uv sync above guarantees this python exists.
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    Write-Error "uv sync finished but $python does not exist."
    exit 1
}
# A token per run. Loopback alone does not keep out other local processes,
# or a web page posting text/plain to 127.0.0.1 (REVIEW.md, 2026-11-10). The
# bridge gets it through its environment, claude as ANTHROPIC_AUTH_TOKEN.
$tokenBytes = [byte[]]::new(32)
[System.Security.Cryptography.RandomNumberGenerator]::Fill($tokenBytes)
$token = [Convert]::ToHexString($tokenBytes)
$authHeader = @{ Authorization = "Bearer $token" }

Write-Host "Starting harness bridge on $baseUrl (model $BridgeModel, small $BridgeSmallModel), expecting it up within ~30 s"
Write-Host "  log: $log"
# Start-Process passes this process's environment on. Set the token only
# around the call, so it does not stay in the caller's session.
$env:BRIDGE_TOKEN = $token
try {
    $proc = Start-Process -FilePath $python -WindowStyle Hidden -PassThru `
        -WorkingDirectory $PSScriptRoot `
        -ArgumentList @((Join-Path $PSScriptRoot 'bridge.py'), '--port', $port, '--model', $BridgeModel, '--small-model', $BridgeSmallModel) `
        -RedirectStandardError $log -RedirectStandardOutput "$log.out"
} catch {
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    throw
} finally {
    Remove-Item Env:BRIDGE_TOKEN -ErrorAction SilentlyContinue
}
# From here line 1 names the bridge; line 2 this PowerShell, which owns it.
Set-Content -Path $pidFile -Value @($proc.Id, $PID)

$saved = @{}
$claudeExit = 1
try {
    $deadline = (Get-Date).AddSeconds(120)
    $up = $false
    while (-not $up) {
        # Checked before the probe: if our bridge died (port taken), an answer
        # on that port comes from someone else's bridge and must not count.
        if ($proc.HasExited) {
            throw "Harness bridge exited with code $($proc.ExitCode) before answering. Last log lines:`n$((Get-Content $log -Tail 15) -join "`n")"
        }
        try {
            # With our token, only our own bridge answers; another bridge on
            # the same port refuses it.
            $r = Invoke-RestMethod -Uri "$baseUrl/v1/models" -Headers $authHeader -TimeoutSec 3
            $up = [bool]$r.data
        } catch {
            $up = $false
        }
        if ($up) {
            break
        }
        if ((Get-Date) -gt $deadline) {
            throw "Harness bridge not answering on $baseUrl after 120 s. See $log"
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Host "Harness bridge up (pid $($proc.Id))."

    # Environment for this claude process only, restored in finally. A cloud
    # provider switch would make Claude Code ignore ANTHROPIC_BASE_URL, and a
    # real ANTHROPIC_API_KEY would be sent to the bridge; both are cleared.
    $vars = [ordered]@{
        ANTHROPIC_BASE_URL                       = $baseUrl
        ANTHROPIC_AUTH_TOKEN                     = $token   # checked by the bridge
        ANTHROPIC_API_KEY                        = $null
        ANTHROPIC_MODEL                          = $BridgeModel
        ANTHROPIC_DEFAULT_OPUS_MODEL             = $BridgeModel
        ANTHROPIC_DEFAULT_SONNET_MODEL           = $BridgeSmallModel
        ANTHROPIC_DEFAULT_HAIKU_MODEL            = $BridgeSmallModel
        ANTHROPIC_SMALL_FAST_MODEL               = $BridgeSmallModel
        CLAUDE_CODE_USE_BEDROCK                  = $null
        CLAUDE_CODE_USE_VERTEX                   = $null
        CLAUDE_CODE_USE_FOUNDRY                  = $null
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC = '1'
        # Auto mode's server-side check never answers through the bridge, and
        # an action without a verdict is refused. With 0, Claude Code sends
        # its own classifier requests instead; they go through the bridge to
        # the small model like any other call (verified 2026-11-10).
        CLAUDE_CODE_AUTO_MODE_SERVER             = '0'
        # claude.ai connectors cannot load with an API key set; this stops
        # Claude Code warning about it at every start (2.1.321).
        ENABLE_CLAUDEAI_MCP_SERVERS              = 'false'
    }
    foreach ($name in $vars.Keys) {
        $saved[$name] = [Environment]::GetEnvironmentVariable($name)
        [Environment]::SetEnvironmentVariable($name, $vars[$name])
    }

    Write-Host "Starting claude on Copilot model $BridgeModel via $baseUrl"
    & claude @ClaudeArgs
    $claudeExit = $LASTEXITCODE
    # Claude Code prints "claude ... --resume <id>" on exit. Run like that it
    # goes to Anthropic, not through the bridge. Its output cannot be
    # rewritten without sitting between the TUI and the terminal, so say it
    # underneath. Headless runs (-p) print no resume hint.
    $headless = $false
    foreach ($a in $ClaudeArgs) {
        if ($a -eq '-p' -or $a -eq '--print') {
            $headless = $true
        }
    }
    if (-not $headless) {
        Write-Host "To resume on Copilot, start it through this launcher instead:"
        Write-Host "  $(Join-Path $PSScriptRoot 'claude-copilot.cmd') --resume <the id above>"
    }
} finally {
    foreach ($name in $saved.Keys) {
        [Environment]::SetEnvironmentVariable($name, $saved[$name])
    }
    # Tear down. Runs on normal exit, Ctrl+C and a failed start alike.
    Write-Host "Stopping harness bridge pid $($proc.Id) and its children on port $port"
    # /T: the venv python.exe is a launcher stub with the real interpreter as
    # its child. Killing only the stub can leave the bridge up.
    & taskkill.exe /PID $proc.Id /T /F 2>&1 | Out-Null
    Remove-Item $pidFile -ErrorAction SilentlyContinue
}
exit $claudeExit
