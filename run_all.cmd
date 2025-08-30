@echo off
setlocal
cd /d "%~dp0"
start "Flask" powershell -NoExit -ExecutionPolicy Bypass -Command ".\env\Scripts\Activate.ps1; $env:FLASK_APP='webapp.app:create_app'; $env:DEV_MODE='true'; flask run --port 8000"
start "Bot" powershell -NoExit -ExecutionPolicy Bypass -Command ".\env\Scripts\Activate.ps1; python .\bot\bot.py"
echo Started Flask and Bot in two windows.
