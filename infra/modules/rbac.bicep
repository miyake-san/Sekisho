metadata name = 'Sekisho RBAC — role assignments to the gateway managed identity'
metadata description = 'Grants the ACA system-assigned managed identity the two data-plane roles it needs: Cognitive Services User on the Foundry account, and Key Vault Secrets Officer on the Key Vault. Implements ADR 0001. Uses native, correctly-scoped extension role assignments.'

targetScope = 'resourceGroup'

@description('Required. Principal (object) ID of the ACA system-assigned managed identity.')
param principalId string

@description('Required. Name of the Foundry (Cognitive Services) account to scope the Cognitive Services User role to.')
param foundryAccountName string

@description('Required. Name of the Key Vault to scope the Key Vault Secrets Officer role to.')
param keyVaultName string

@description('Optional. Principal type. "ServicePrincipal" is correct for a managed identity.')
param principalType string = 'ServicePrincipal'

// Built-in role definition GUIDs (ADR 0001). Parameterized because some tenants (e.g. certain
// MCAP/sandbox subscriptions) expose these same-named roles under DIFFERENT definition GUIDs;
// override these to the values from `az role definition list --name "<role>" --query "[].name"`.
@description('Optional. Role definition GUID for "Cognitive Services User" in the target tenant.')
param cognitiveServicesUserRoleId string = 'a97b65f3-24c7-4388-baec-2e87618995b6'

@description('Optional. Role definition GUID for "Key Vault Secrets Officer" in the target tenant.')
param keyVaultSecretsOfficerRoleId string = 'b86a8fe4-44ce-4948-aee7-ecce2b3f48c9'

// Reference the existing targets so each role assignment is scoped as an extension resource on them.
resource foundry 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: foundryAccountName
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

// Lets the gateway call the Foundry data plane with its managed identity (Entra-only access).
resource cognitiveServicesUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, principalId, cognitiveServicesUserRoleId)
  scope: foundry
  properties: {
    principalId: principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalType: principalType
  }
}

// Lets the gateway list / create / rotate / revoke Sekisho Keys (stored as Key Vault secrets).
resource keyVaultSecretsOfficer 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, principalId, keyVaultSecretsOfficerRoleId)
  scope: keyVault
  properties: {
    principalId: principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsOfficerRoleId)
    principalType: principalType
  }
}

@description('Resource ID of the Cognitive Services User role assignment.')
output cognitiveServicesUserAssignmentId string = cognitiveServicesUser.id

@description('Resource ID of the Key Vault Secrets Officer role assignment.')
output keyVaultSecretsOfficerAssignmentId string = keyVaultSecretsOfficer.id
