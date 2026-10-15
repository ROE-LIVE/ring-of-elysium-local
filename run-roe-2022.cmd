@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\bootstrap.ps1" %*
set "ROE_EXIT=%ERRORLEVEL%"
if not "%ROE_EXIT%"=="0" (
  echo.
  echo ROE launch failed. See runs and the message above.
  pause
)
exit /b %ROE_EXIT%
