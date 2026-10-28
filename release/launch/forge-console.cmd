@echo off
rem Forge with a console window: its log shows here. Try: forge-console.cmd --help
set PYTHONDONTWRITEBYTECODE=1
"%~dp0runtime\python.exe" "%~dp0forge_portable.py" %*
