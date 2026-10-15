@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\reset_local.ps1" %*
exit /b %ERRORLEVEL%
