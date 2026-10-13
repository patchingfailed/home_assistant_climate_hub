# Copy as scripts/deploy.config.ps1 (gitignored) and fill in real values.
# The ONLY place IPs/tokens are allowed to live.

$DevHost  = "<dev-host-ip>"
$ProdHost = "<prod-host-ip>"          # only use after explicit approval

# SMB share onto the HA config directory (Samba add-on)
$DevTarget  = "\\$DevHost\config\custom_components\climate_hub"
$ProdTarget = "\\$ProdHost\config\custom_components\climate_hub"

# Long-lived access token (HA profile -> Security) for REST: restart/reload/logs.
# DEV: env var HA_DEV_TOKEN, else HA_TOKEN from the repo's .env (gitignored, also read by ha.py).
$EnvFile = Join-Path (Split-Path $PSScriptRoot -Parent) ".env"
$DotEnv = @{}
if (Test-Path -LiteralPath $EnvFile) {
  Get-Content -LiteralPath $EnvFile | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { $DotEnv[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'") }
  }
}
$DevToken  = if ($env:HA_DEV_TOKEN) { $env:HA_DEV_TOKEN } else { $DotEnv["HA_TOKEN"] }
$ProdToken = $env:HA_PROD_TOKEN
