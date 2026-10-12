# Copy as scripts/deploy.config.ps1 (gitignored) and fill in real values.
# The ONLY place IPs/tokens are allowed to live.

$DevHost  = "<dev-host-ip>"
$ProdHost = "<prod-host-ip>"          # only use after explicit approval

# SMB share onto the HA config directory (Samba add-on)
$DevTarget  = "\\$DevHost\config\custom_components\climate_hub"
$ProdTarget = "\\$ProdHost\config\custom_components\climate_hub"

# Long-lived access token (HA profile -> Security) for REST: restart/reload/logs.
# Alternatively leave empty and set the HA_DEV_TOKEN / HA_PROD_TOKEN env vars.
$DevToken  = $env:HA_DEV_TOKEN
$ProdToken = $env:HA_PROD_TOKEN
