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

if ($BridgeStop) {
    # Normal runs clean up after themselves. A pid file left behind means a
    # session ended without reaching its cleanup (window closed, killed).
    $pidFiles = @(Get-ChildItem -Path $logDir -Filter 'bridge-*.pid' -ErrorAction SilentlyContinue)
    if ($pidFiles.Count -eq 0) {
        Write-Host "No orphaned harness bridges (no pid files in $logDir)."
        exit 0
    }
    foreach ($f in $pidFiles) {
        $orphanPid = [int](Get-Content $f.FullName)
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
    # A pid file marks a port as taken from the moment a bridge is launched,
    # before it binds: a second session starting in that gap would otherwise
    # pick the same port.
    if (Test-Path (Join-Path $logDir "bridge-$candidate.pid")) {
        continue
    }
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $candidate)
    try {
        $listener.Start()
        $listener.Stop()
        $port = $candidate
        break
    } catch {
        continue
    }
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
    Write-Error "uv sync failed (exit $LASTEXITCODE) in $PSScriptRoot"
    exit 1
}

# Start the venv's python directly, not `uv run`. The `uv` on PATH may be a
# winget link that relaunches the real uv and exits at once: Start-Process
# then returns a pid that is already gone, and teardown misses the bridge
# (TODONT.md). uv sync above guarantees this python exists.
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
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
} finally {
    Remove-Item Env:BRIDGE_TOKEN -ErrorAction SilentlyContinue
}
Set-Content -Path $pidFile -Value $proc.Id

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
