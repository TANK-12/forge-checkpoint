@echo off
rem Forge: starts the hub with the Python bundled beside this file.
rem forge-console.cmd does the same with a console window, for --help and --smoke.
set PYTHONDONTWRITEBYTECODE=1
start "" "%~dp0runtime\pythonw.exe" "%~dp0forge_portable.py" %*
