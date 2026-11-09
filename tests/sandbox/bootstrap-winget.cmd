@echo off
rem Windows Sandbox ships without winget and without the Store. This is
rem Microsoft's documented bootstrap, run in Windows PowerShell 5.1:
rem https://learn.microsoft.com/en-us/windows/package-manager/winget/
echo Installing winget in this sandbox, expect a minute or two...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Install-PackageProvider -Name NuGet -Force | Out-Null; Install-Module -Name Microsoft.WinGet.Client -Force -Repository PSGallery | Out-Null; Repair-WinGetPackageManager -AllUsers; Write-Host 'winget bootstrap done.'"
echo.
echo Open a NEW terminal before running install-windows.bat again.
pause
