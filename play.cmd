@echo off
setlocal
call "%~dp0run-roe-2022.cmd" -Kit glider -Mode cycle -CycleScale 3 -Duration 1500 -ReliableUDP -IdleHandoff -WinterDoors -WinterWindows -DebugConsole -Target armored -LootCatalog "%~dp0config\windows-smoke-20261015.json" %*
exit /b %ERRORLEVEL%
