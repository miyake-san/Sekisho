<#
.SYNOPSIS
    Sets the Sekisho admin password (app-level login, no Entra) on the Container App
    and rolls out a new revision so it takes effect.

.DESCRIPTION
    Sekisho's /admin uses an app-level password login when ADMIN_PASSWORD is set.
    This script stores the password in the Container App secret 'admin-password'
    and forces a NEW revision (Container Apps mounts secrets at revision creation,
    so a restart alone does not reload a changed secret value).

    The password value is never printed. You will be prompted to type it securely.

.EXAMPLE
    ./set-admin-password.ps1 -SubscriptionId 401f453f-7b92-4e20-9c55-265205a1b26f
#>
[CmdletBinding()]
param(
    [string] $ResourceGroup = "rg-sekisho",
    [string] $ContainerApp  = "sekisho-gw-uwp7nk",
    [string] $SubscriptionId = "401f453f-7b92-4e20-9c55-265205a1b26f"
)

$ErrorActionPreference = "Stop"

function Write-Step([string] $Message) { Write-Host "==> $Message" -ForegroundColor Cyan }

# Prompt for the password securely (never echoed, never passed through chat).
$secure = Read-Host -AsSecureString "New Sekisho admin password"
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
if (-not $plain -or $plain.Length -lt 12) {
    throw "Password must be at least 12 characters."
}

Write-Step "Updating Container App secret 'admin-password' on $ContainerApp"
az containerapp secret set --resource-group $ResourceGroup --name $ContainerApp `
    --subscription $SubscriptionId --secrets "admin-password=$plain" --output none
$plain = $null

# Force a NEW revision so the running replicas pick up the changed secret value.
$suffix = "pw" + (Get-Date -Format "MMddHHmm")
Write-Step "Rolling out new revision (suffix $suffix)"
az containerapp update --resource-group $ResourceGroup --name $ContainerApp `
    --subscription $SubscriptionId --revision-suffix $suffix --output none

Write-Host ""
Write-Host "OK: admin password updated. Open https://<gateway-fqdn>/admin/login in a fresh window." -ForegroundColor Green
