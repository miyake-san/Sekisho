metadata name = 'Sekisho Key Vault (Key store)'
metadata description = 'RBAC-authorized, soft-delete-enabled Key Vault that backs the Sekisho "Key store". Sekisho Keys are stored as Key Vault secrets; the gateway managed identity is granted Key Vault Secrets Officer via rbac.bicep. Implements ADR 0001.'

@description('Required. Key Vault name (3-24 chars, globally unique).')
param name string

@description('Optional. Location for the Key Vault.')
param location string = resourceGroup().location

@description('Optional. SKU. "standard" is sufficient because Sekisho Keys are stored as secrets (not HSM-backed keys).')
@allowed([
  'standard'
  'premium'
])
param sku string = 'standard'

@description('Optional. Soft-delete retention in days.')
@minValue(7)
@maxValue(90)
param softDeleteRetentionInDays int = 90

@description('Optional. Enable purge protection. Off by default for easy POC teardown; turn ON for production.')
param enablePurgeProtection bool = false

@description('Optional. Tags to apply to the vault.')
param tags object = {}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    tenantId: tenant().tenantId
    sku: {
      family: 'A'
      name: sku
    }
    enableRbacAuthorization: true // RBAC authorization, NOT access policies (ADR 0001)
    enableSoftDelete: true
    softDeleteRetentionInDays: softDeleteRetentionInDays
    // Key Vault rejects an explicit "false" for purge protection, so send null when disabled.
    enablePurgeProtection: enablePurgeProtection ? true : null
    publicNetworkAccess: 'Enabled'
  }
}

@description('Resource ID of the Key Vault.')
output vaultId string = vault.id

@description('Name of the Key Vault.')
output vaultName string = vault.name

@description('URI of the Key Vault (KEY_VAULT_URI for the gateway).')
output vaultUri string = vault.properties.vaultUri