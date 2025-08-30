@echo off
setlocal
cd /d "%~dp0"

rem 1) Find ngrok
where ngrok >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
  if exist "%~dp0ngrok.exe" (
    set "NGROK=%~dp0ngrok.exe"
  ) else (
    echo [ERROR] ngrok not found. Please install from https://ngrok.com/download ^& ensure it is in PATH or place ngrok.exe in this folder:
    echo         %~dp0
    echo Then re-run: start_https.cmd
    exit /b 1
  )
)

rem 2) Start ngrok (http 8000) in a separate window
if not defined NGROK set "NGROK=ngrok"
start "ngrok" "%NGROK%" http 8000
echo Waiting for ngrok tunnel...

rem 3) Poll ngrok local API for https public URL
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File ".\scripts\get_ngrok_https.ps1"
if %ERRORLEVEL% NEQ 0 (
  echo [ERROR] Could not fetch https URL from ngrok (is it running?)
  exit /b 2
)

for /f "usebackq delims=" %%A in (`powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\get_ngrok_https.ps1`) do set "PUBLIC_URL=%%A"
echo Found PUBLIC_URL=%PUBLIC_URL%

rem 4) Update .env APP_URL and restart bot
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -Command ".\env\Scripts\Activate.ps1; .\scripts\update_env_app_url.ps1 -EnvPath '.\.env' -AppUrl '%PUBLIC_URL%'"

rem Kill any running bot processes
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process ^| Where-Object { $_.CommandLine -match 'bot\\bot.py' } ^| ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }"

rem Start bot again
start "Bot" powershell -NoExit -ExecutionPolicy Bypass -Command ".\env\Scripts\Activate.ps1; python .\bot\bot.py"
echo HTTPS is configured. Bot restarted with APP_URL=%PUBLIC_URL%

