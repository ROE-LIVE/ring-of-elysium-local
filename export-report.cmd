@echo off
setlocal
if not exist "%~dp0.tools\python\python.exe" (
  echo First run run-roe-2022.cmd to prepare local Python.
  exit /b 1
)
"%~dp0.tools\python\python.exe" -X utf8 -B "%~dp0tools\export_test_report_2022.py" %*
exit /b %errorlevel%
