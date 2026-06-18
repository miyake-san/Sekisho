<#
.SYNOPSIS
    Rotates the Microsoft Entra (Easy Auth) client secret used by the Sekisho
    Container App, then reloads it.

.DESCRIPTION
    Some Entra tenants enforce a maximum app-secret lifetime (for example 30 days)
    via an app management policy. When the secret expires, Easy Auth can no longer
    complete the OAuth code exchange and /admin returns HTTP 401.

    This script:
      1. Creates a fresh client secret on the app registration (within the policy limit).
      2. Updates the Container App secret that Easy Auth references by name.
      3. Forces a NEW revision so the Easy Auth sidecar mounts the new secret.
      4. Verifies the new credential and prints its expiry.

    IMPORTANT: Container Apps mounts secrets at REVISION CREATION time. Restarting
    the same revision does NOT reload an updated secret value, so a new revision
    must be created or the auth sidecar keeps using the old (now-invalid) secret
    and /admin keeps returning HTTP 401 at /.auth/login/aad/callback.

    The secret value is never printed. Requires the Azure CLI (az), logged in to the
    correct tenant/subscription with rights to manage the app registration and the
    Container App.

.EXAMPLE
    ./rotate-easyauth-secret.ps1

.EXAMPLE
    ./rotate-easyauth-secret.ps1 -ResourceGroup rg-sekisho -ContainerApp sekisho-gw-xxxx -AppId <guid> -Days 29
#>
[CmdletBinding()]
param(
    [string] $ResourceGroup = "rg-sekisho",
    [string] $ContainerApp  = "sekisho-gw-gnuriz",
    [string] $AppId         = "a7ceb3c3-62ff-44a2-974f-6bba6af83b83",
    [string] $SecretName    = "aad-client-secret",
    [int]    $Days          = 29,
    [string] $SubscriptionId
)

$ErrorActionPreference = "Stop"

function Write-Step([string] $Message) { Write-Host "==> $Message" -ForegroundColor Cyan }

if ($SubscriptionId) {
    Write-Step "Selecting subscription $SubscriptionId"
    az account set --subscription $SubscriptionId | Out-Null
}

# 1) Create a new secret within the tenant policy limit.
$endDate = (Get-Date).ToUniversalTime().AddDays($Days).ToString("yyyy-MM-ddTHH:mm:ssZ")
Write-Step "Resetting Entra client secret on app $AppId (expires $endDate)"
$secret = az ad app credential reset --id $AppId --display-name "easyauth" --end-date $endDate --query password -o tsv
if (-not $secret -or $secret.Length -lt 20 -or $secret -match "ERROR") {
    throw "Failed to create client secret. If you see a credential-lifetime policy error, lower -Days. Output: $secret"
}
Write-Host "    New secret created (length $($secret.Length))."

# 2) Update the Container App secret that Easy Auth references by name.
Write-Step "Updating Container App secret '$SecretName' on $ContainerApp"
az containerapp secret set --resource-group $ResourceGroup --name $ContainerApp --secrets "$SecretName=$secret" --output none

# 3) Force a NEW revision so the auth sidecar mounts the updated secret.
#    (Restarting the same revision does NOT reload a changed secret value.)
$suffix = "s" + (Get-Date -Format "MMddHHmm")
Write-Step "Creating new revision (suffix $suffix) to load the rotated secret"
az containerapp update --resource-group $ResourceGroup --name $ContainerApp --revision-suffix $suffix --output none

# 4) Verify and clean up.
$secret = $null
$expiry = az ad app credential list --id $AppId --query "[0].endDateTime" -o tsv
Write-Host ""
Write-Host "OK: rotation complete. Active Entra secret expiry: $expiry" -ForegroundColor Green
Write-Host "    Retry https://<gateway-fqdn>/admin in a fresh/incognito window." -ForegroundColor Green
