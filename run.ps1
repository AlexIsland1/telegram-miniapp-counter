param()

$ErrorActionPreference = 'Stop'
$wd = Split-Path -Parent $MyInvocation.MyCommand.Path

$flaskCmd = ".\\env\\Scripts\\Activate.ps1; `$env:FLASK_APP='webapp.app'; `$env:DEV_MODE='true'; flask run --port 8000"
$botCmd   = ".\\env\\Scripts\\Activate.ps1; python .\\bot\\bot.py"

Start-Process powershell -ArgumentList '-NoExit','-Command', $flaskCmd -WorkingDirectory $wd | Out-Null
Start-Process powershell -ArgumentList '-NoExit','-Command', $botCmd -WorkingDirectory $wd   | Out-Null

Write-Host 'Started Flask and Bot in separate PowerShell windows.'
Write-Host 'Flask: http://localhost:8000  (dev-mode allows ?user_id=123)'

