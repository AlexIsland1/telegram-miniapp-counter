param(
  [int]$Tries = 30,
  [int]$DelayMs = 500
)

$ErrorActionPreference = 'SilentlyContinue'
for ($i=0; $i -lt $Tries; $i++) {
  try {
    $resp = Invoke-RestMethod -Uri 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 2
    foreach ($t in $resp.tunnels) {
      if ($t.public_url -like 'https://*') { Write-Output $t.public_url; exit 0 }
    }
  } catch {}
  Start-Sleep -Milliseconds $DelayMs
}
exit 1

