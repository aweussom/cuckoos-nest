@echo off
rem Runs claude-copilot.ps1 from cmd, Explorer or a PATH entry.
rem ExecutionPolicy Bypass: a downloaded .ps1 is blocked by the default
rem policy on many machines, and this script is the one you meant to run.
rem Arguments pass through unchanged (-p "...", -c, -BridgeModel ...).
where /q pwsh
if errorlevel 1 (
    echo PowerShell 7 not found. Run install-windows.bat in this directory first.
    exit /b 1
)
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0claude-copilot.ps1" %*
exit /b %ERRORLEVEL%
