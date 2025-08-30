@echo off
setlocal
cd /d "%~dp0"
powershell -NoExit -ExecutionPolicy Bypass -Command ".\env\Scripts\Activate.ps1; python .\bot\bot.py"

