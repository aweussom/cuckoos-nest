@echo off
rem Runs at sandbox logon. Copies the read-only mapped repo to a short local
rem path (install-windows.bat refuses long paths) without .venv, logs, .git.
robocopy C:\src\cuckoos-nest C:\cuckoos-nest /E /XD .venv logs .git __pycache__ .copilot-runtime /NFL /NDL /NJH /NJS >nul
start "" explorer C:\cuckoos-nest
