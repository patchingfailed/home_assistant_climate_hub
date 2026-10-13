# Deploys ONLY custom_components/climate_hub to a HA instance, optionally
# restarting / fetching logs over the REST API.
#
#   .\scripts\deploy.ps1                 # DEV, copy only
#   .\scripts\deploy.ps1 -Restart        # DEV, copy + HA restart
#   .\scripts\deploy.ps1 -Logs           # DEV, climate_hub log lines only
#   .\scripts\deploy.ps1 -Instance Prod  # Prod -> asks for explicit confirmation
#
# Reload is enough for pure logic/flow changes (UI: Integration -> Reload).
# Restart is needed for: new file, manifest.json, new platform, translations.

param(
  [ValidateSet("Dev", "Prod")] [string]$Instance = "Dev",
  [switch]$Restart,
  [switch]$Logs
)

$ErrorActionPreference = "Stop"
$ConfigFile = Join-Path $PSScriptRoot "deploy.config.ps1"
if (-not (Test-Path -LiteralPath $ConfigFile)) {
  throw "Missing: $ConfigFile (copy deploy.config.example.ps1 as a template)"
}
. $ConfigFile

if ($Instance -eq "Prod") {
  $answer = Read-Host "Really deploy to PROD ($ProdHost)? (yes/no)"
  if ($answer -ne "yes") { Write-Host "Aborted."; exit 1 }
  $HostName = $ProdHost; $Target = $ProdTarget; $Token = $ProdToken
} else {
  $HostName = $DevHost; $Target = $DevTarget; $Token = $DevToken
}

$BaseUrl = "http://${HostName}:8123"
$Headers = @{ Authorization = "Bearer $Token"; "Content-Type" = "application/json" }

if ($Logs) {
  if (-not $Token) { throw "No token configured." }
  $log = Invoke-RestMethod -Uri "$BaseUrl/api/error_log" -Headers $Headers -Method Get
  $log -split "`n" | Where-Object { $_ -match "climate_hub" } | Select-Object -Last 50
  exit 0
}

$Source = Join-Path (Split-Path $PSScriptRoot -Parent) "custom_components\climate_hub"
if (-not (Test-Path -LiteralPath $Source)) { throw "Source not found: $Source" }

# /MIR only on the integration folder (deletes in the target what's missing in the source).
robocopy $Source $Target /MIR /FFT /R:2 /W:2 /XD __pycache__ /XF *.pyc | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed (exit $LASTEXITCODE)" }
Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Deployed -> $Target"

if ($Restart) {
  if (-not $Token) { throw "No token configured - restart manually via the UI." }
  # HA often closes the connection while it restarts, so a failed call here is expected.
  try {
    Invoke-RestMethod -Uri "$BaseUrl/api/services/homeassistant/restart" -Headers $Headers -Method Post -TimeoutSec 30 | Out-Null
  } catch {
    Write-Host "Restart call ended early (expected while HA restarts)."
  }
  Write-Host "Restart of $HostName triggered, waiting for HA ..."
  Start-Sleep -Seconds 10
  $deadline = (Get-Date).AddMinutes(5)
  while ((Get-Date) -lt $deadline) {
    try {
      $cfg = Invoke-RestMethod -Uri "$BaseUrl/api/config" -Headers $Headers -TimeoutSec 5
      if ($cfg.state -eq "RUNNING") { Write-Host "HA is running again."; exit 0 }
    } catch { }
    Start-Sleep -Seconds 5
  }
  throw "HA did not report RUNNING within 5 minutes."
}
