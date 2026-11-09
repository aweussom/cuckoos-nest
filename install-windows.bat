@echo off
rem ===========================================================================
rem  install-windows.bat -- cuckoos-nest setup for people who just cloned or
rem  downloaded a ZIP.
rem
rem  Double-click this file. It checks for PowerShell 7, uv, Claude Code and
rem  the Copilot CLI, offers to install whatever is missing via winget, then
rem  sets up the Python environment with uv and offers `copilot login`.
rem
rem  Why a .bat: Windows ships PowerShell 5.1, which cannot run
rem  claude-copilot.ps1 (#requires 7.0), and scripts from a downloaded ZIP are
rem  blocked by execution policy. A .bat has neither problem.
rem
rem  Based on NoLlama's install-windows.bat. Safe to run again.
rem ===========================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title cuckoos-nest install
echo.
echo  === cuckoos-nest install (Windows) ===
echo.

rem --- 0. Where are we? OneDrive, spaces and long paths break Python venvs
rem        in ways nobody wants to debug. Refuse early.
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
call :pathcheck "%HERE%"
if errorlevel 1 goto :fail

rem --- 1. PowerShell 7 ------------------------------------------------------
set "PWSH="
where pwsh >nul 2>nul && set "PWSH=pwsh"
if not defined PWSH if exist "%ProgramFiles%\PowerShell\7\pwsh.exe" set "PWSH=%ProgramFiles%\PowerShell\7\pwsh.exe"
rem winget may pick the MSIX package (seen in Windows Sandbox, 7.6.9): no
rem Program Files folder, only a 0-byte app execution alias in WindowsApps.
if not defined PWSH if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\pwsh.exe" set "PWSH=%LOCALAPPDATA%\Microsoft\WindowsApps\pwsh.exe"

if not defined PWSH (
    echo  PowerShell 7 is not installed. Windows ships 5.1, which is too old.
    echo.
    echo  The command to install it:
    echo.
    echo      winget install --id Microsoft.PowerShell --source winget
    echo.
    where winget >nul 2>nul
    if errorlevel 1 (
        echo  ...but 'winget' was not found either. Two options:
        echo    a^) Install "App Installer" from the Microsoft Store: https://aka.ms/getwinget
        echo    b^) Download PowerShell 7 directly: https://aka.ms/powershell-release?tag=stable
        echo  Then double-click this file again.
        goto :fail
    )
    choice /C YN /M "  Run it now"
    if errorlevel 2 goto :fail
    winget install --id Microsoft.PowerShell --source winget
    if exist "%ProgramFiles%\PowerShell\7\pwsh.exe" set "PWSH=%ProgramFiles%\PowerShell\7\pwsh.exe"
    if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\pwsh.exe" set "PWSH=%LOCALAPPDATA%\Microsoft\WindowsApps\pwsh.exe"
    if not defined PWSH (
        echo.
        echo  Installed, but this window's PATH is stale. Close this window and
        echo  double-click install-windows.bat again.
        goto :fail
    )
)
echo  [+] PowerShell 7 found.

rem --- 2. uv ----------------------------------------------------------------
rem uv brings its own Python, so there is no Python check here. After a
rem winget install the PATH of this window is stale; winget puts a link in
rem WinGet\Links, the standalone installer uses .local\bin. Look there too.
set "UV="
where uv >nul 2>nul && set "UV=uv"
if not defined UV if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe" set "UV=%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe"
if not defined UV if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"

if not defined UV (
    echo  uv is not installed. It manages Python and the dependencies.
    echo.
    echo  The command to install it:
    echo.
    echo      winget install --id astral-sh.uv --source winget
    echo.
    choice /C YN /M "  Run it now"
    if errorlevel 2 goto :fail
    winget install --id astral-sh.uv --source winget
    if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe" (
        set "UV=%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe"
    ) else (
        echo.
        echo  Installed, but this window's PATH is stale. Close this window and
        echo  double-click install-windows.bat again.
        goto :fail
    )
)
echo  [+] uv found.

rem --- 3. Claude Code ---------------------------------------------------------
rem claude-copilot.ps1 runs `claude` by name, so it has to be on PATH in the
rem terminal you start it from. A fresh install is, in a new window.
set "CLAUDE_NEW="
where claude >nul 2>nul
if errorlevel 1 (
    echo  Claude Code is not installed.
    echo.
    echo  The command to install it:
    echo.
    echo      winget install --id Anthropic.ClaudeCode --source winget
    echo.
    choice /C YN /M "  Run it now"
    if errorlevel 2 goto :fail
    winget install --id Anthropic.ClaudeCode --source winget
    if errorlevel 1 (
        echo  winget did not install Claude Code.
        goto :fail
    )
    set "CLAUDE_NEW=1"
)
echo  [+] Claude Code found.

rem --- 4. Copilot CLI (only for `copilot login`) ----------------------------
rem The bridge uses the Copilot SDK, which brings its own runtime. The CLI is
rem only the easy way to log in once. Skip it if this machine already has a
rem Copilot CLI or SDK login.
set "COPILOT="
where copilot >nul 2>nul && set "COPILOT=copilot"
if not defined COPILOT if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\copilot.exe" set "COPILOT=%LOCALAPPDATA%\Microsoft\WinGet\Links\copilot.exe"
rem winget's GitHub.Copilot installs here, not in WinGet\Links (seen in
rem Windows Sandbox 2026-11-09). Missing it skipped the login step silently.
if not defined COPILOT if exist "%LOCALAPPDATA%\GitHubCopilotCLI\copilot.exe" set "COPILOT=%LOCALAPPDATA%\GitHubCopilotCLI\copilot.exe"

if not defined COPILOT (
    echo  The Copilot CLI is not installed. You need it once, for `copilot login`,
    echo  unless this machine already has a Copilot login.
    echo.
    echo      winget install --id GitHub.Copilot --source winget
    echo.
    choice /C YN /M "  Install it now"
    if errorlevel 2 goto :skipcopilot
    winget install --id GitHub.Copilot --source winget
    if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\copilot.exe" set "COPILOT=%LOCALAPPDATA%\Microsoft\WinGet\Links\copilot.exe"
    if exist "%LOCALAPPDATA%\GitHubCopilotCLI\copilot.exe" set "COPILOT=%LOCALAPPDATA%\GitHubCopilotCLI\copilot.exe"
    if not defined COPILOT (
        echo.
        echo  [!] Copilot CLI installed, but this window cannot find it ^(stale PATH^).
        echo      After this script, open a NEW terminal and run:  copilot login
        echo      The bridge fails with "Not authenticated" until you do.
    )
)
:skipcopilot
if defined COPILOT echo  [+] Copilot CLI found.

rem --- 5. Python environment --------------------------------------------------
echo.
echo  Setting up the Python environment with uv ^(first run downloads Python
echo  and the dependencies from uv.lock^)...
echo.
"%UV%" sync --frozen
if errorlevel 1 (
    echo  uv sync failed.
    goto :fail
)
echo  [+] Python environment ready.

rem --- 6. Copilot login -------------------------------------------------------
if defined COPILOT (
    echo.
    echo  If you have never logged in to Copilot on this machine, do it now.
    echo  It opens github.com/login/device and waits for you there.
    choice /C YN /M "  Run 'copilot login' now"
    if not errorlevel 2 "!COPILOT!" login
)

:done
echo.
echo  Done. From any project directory, run:
echo.
echo      "%~dp0claude-copilot.cmd"
echo.
if defined CLAUDE_NEW echo  Claude Code was just installed: open a NEW terminal first, so it is on PATH.
pause
exit /b 0

:fail
echo.
pause
exit /b 1

:pathcheck
rem %~1 is the folder this script lives in. Fail on OneDrive, on spaces, and
rem on anything longer than 60 characters. The fix is always the same: move
rem the folder somewhere short, like C:\cuckoos-nest, and run this again.
rem !BAD! (not %BAD%) inside the block below: a %-expanded ")" would close it.
set "P=%~1"
set "BAD="
if not "%P%"=="%P:OneDrive=%" set "BAD=it is inside OneDrive"
if not "%P%"=="%P: =%" set "BAD=it has a space in it"
set "N=0"
for /L %%i in (0,1,200) do if not "!P:~%%i,1!"=="" set /a N=%%i+1
if %N% GTR 60 set "BAD=it is %N% characters long, limit 60"
if defined BAD (
    echo  This folder is:  !P!
    echo  Not going to install here, because !BAD!.
    echo.
    echo  Move the whole cuckoos-nest folder to   C:\cuckoos-nest
    echo  and double-click install-windows.bat there.
    exit /b 1
)
echo  [+] Folder is fine: %P%
exit /b 0
