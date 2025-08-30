@echo off
echo === NGROK SETUP FOR TELEGRAM BOT ===
echo.
echo Step 1: Download ngrok
echo Go to: https://ngrok.com/download
echo Download "Windows (AMD64)" version
echo Place ngrok.exe in this folder: %~dp0
echo.
echo Step 2: Get your bot token
echo Go to @BotFather in Telegram
echo Copy your bot token to .env file (BOT_TOKEN=...)
echo.
echo Step 3: Start ngrok
echo Run: ngrok http 8000
echo Copy the https:// URL (like https://abc123.ngrok-free.app)
echo.
echo Step 4: Update .env
echo Replace APP_URL=https://example.ngrok.io with your ngrok URL
echo.
echo Step 5: Start everything
echo Run: run_all.cmd
echo.
echo Press any key when you're ready...
pause
start https://ngrok.com/download
notepad .env