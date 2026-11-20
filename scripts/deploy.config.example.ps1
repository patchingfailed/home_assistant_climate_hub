# Copy as scripts/deploy.config.ps1 (gitignored). It needs no edits: URLs and tokens come from
# ~/.config/ha/instances.env (outside every repo), keys HA_DEV_URL, HA_DEV_TOKEN, HA_PROD_URL, HA_PROD_TOKEN.
# Environment variables of the same name take precedence over the file.

$InstancesFile = Join-Path $HOME ".config\ha\instances.env"
$Instances = @{}
if (Test-Path -LiteralPath $InstancesFile) {
  Get-Content -LiteralPath $InstancesFile | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { $Instances[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'") }
  }
}
function Get-InstanceValue([string]$Key) {
  $fromEnv = [Environment]::GetEnvironmentVariable($Key)
  if ($fromEnv) { $fromEnv } else { $Instances[$Key] }
}

$DevUrl   = (Get-InstanceValue "HA_DEV_URL").TrimEnd("/")
$ProdUrl  = (Get-InstanceValue "HA_PROD_URL").TrimEnd("/")   # only use after explicit approval
$DevHost  = ([Uri]$DevUrl).Host
$ProdHost = ([Uri]$ProdUrl).Host

# SMB share onto the HA config directory (Samba app)
$DevTarget  = "\\$DevHost\config\custom_components\climate_hub"
$ProdTarget = "\\$ProdHost\config\custom_components\climate_hub"

# Long-lived access tokens (HA profile -> Security) for REST: restart, reload, logs
$DevToken  = Get-InstanceValue "HA_DEV_TOKEN"
$ProdToken = Get-InstanceValue "HA_PROD_TOKEN"
