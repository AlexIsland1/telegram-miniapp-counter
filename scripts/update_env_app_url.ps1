param(
  [Parameter(Mandatory=$true)][string]$EnvPath,
  [Parameter(Mandatory=$true)][string]$AppUrl
)

$ErrorActionPreference = 'Stop'
$content = Get-Content -LiteralPath $EnvPath -Raw -ErrorAction Stop
if ($content -notmatch "(?m)^APP_URL=") {
  $content = $content.TrimEnd() + "`nAPP_URL=$AppUrl`n"
} else {
  $content = [System.Text.RegularExpressions.Regex]::Replace($content, "(?m)^APP_URL=.*$", "APP_URL=$AppUrl")
}
Set-Content -LiteralPath $EnvPath -Value $content -Encoding UTF8 -Force
Write-Output "APP_URL set to $AppUrl in $EnvPath"

