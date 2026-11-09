#requires -Version 5.1
# Writes logs\cuckoos-nest.wsb for a clean-machine test of install-windows.bat
# in Windows Sandbox, then opens it. The .wsb holds this machine's repo path,
# so it is generated into logs\ (gitignored) instead of being committed.
#
# Needs Windows Sandbox enabled (Windows 11 Pro/Enterprise, admin, reboot):
#   Enable-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM -All
#
# Inside the sandbox:
#   1. C:\cuckoos-nest\install-windows.bat   -> should stop: winget not found
#   2. C:\tests\bootstrap-winget.cmd         -> installs winget (Microsoft's
#                                               documented Sandbox method)
#   3. C:\cuckoos-nest\install-windows.bat   -> the winget installs, the
#                                               stale-PATH restarts, uv sync,
#                                               copilot login
#   4. a new terminal, then from any folder: C:\cuckoos-nest\claude-copilot.cmd
#
# The repo is mapped read-only and copied to C:\cuckoos-nest at logon, so the
# sandbox never writes into your checkout (its .venv would replace yours).

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$tests = $PSScriptRoot
$out = Join-Path $repo 'logs'
New-Item -ItemType Directory -Force $out | Out-Null
$wsb = Join-Path $out 'cuckoos-nest.wsb'
# The one writable mapping: the sandbox clipboard is unreliable (it died both
# ways mid-test on 2026-11-09), so results go to a file the host can read.
$results = Join-Path $out 'sandbox-out'
New-Item -ItemType Directory -Force $results | Out-Null

$xml = @"
<Configuration>
  <Networking>Enable</Networking>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>$repo</HostFolder>
      <SandboxFolder>C:\src\cuckoos-nest</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
    <MappedFolder>
      <HostFolder>$tests</HostFolder>
      <SandboxFolder>C:\tests</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
    <MappedFolder>
      <HostFolder>$results</HostFolder>
      <SandboxFolder>C:\out</SandboxFolder>
      <ReadOnly>false</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>C:\tests\sandbox-logon.cmd</Command>
  </LogonCommand>
</Configuration>
"@
Set-Content -Path $wsb -Value $xml -Encoding UTF8
Write-Host "Wrote $wsb"

if (-not (Test-Path "$env:windir\System32\WindowsSandbox.exe")) {
    Write-Host "Windows Sandbox is not enabled on this machine. As admin, then reboot:"
    Write-Host "  Enable-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM -All"
    exit 1
}
Start-Process $wsb
