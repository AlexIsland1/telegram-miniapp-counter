@echo off
echo Starting Spaced Repetition Scheduler...

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo Python is not installed or not in PATH
    pause
    exit /b 1
)

REM Check if virtual environment exists
if exist "env\Scripts\activate.bat" (
    echo Activating virtual environment...
    call env\Scripts\activate.bat
) else (
    echo Virtual environment not found, using system Python
)

REM Install dependencies if needed
echo Installing/updating dependencies...
pip install -r requirements.txt >nul 2>&1

REM Run the scheduler
echo Starting scheduler...
python scheduler.py

pause