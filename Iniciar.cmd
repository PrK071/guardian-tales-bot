@echo off
cd /d "%~dp0"
"%~dp0tools\python\python.exe" -X utf8 "%~dp0launcher.py"
if errorlevel 1 pause
