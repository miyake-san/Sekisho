metadata name = 'Sekisho — managed-identity reverse-proxy gateway to Microsoft Foundry'
metadata description = 'Orchestrates the Sekisho v1 infrastructure: the Foundry account (Entra-only + audio models), the Key Vault Key store, the ACA gateway (system-assigned managed identity + Easy Auth), and the RBAC role assignments that bind them. Implements ADRs 0001, 0002 and 0003.'

targetScope = 'resourceGroup'

@description('Optional. Location for all resources. NOTE: the ADR 0002 audio models (gpt-4o-mini-transcribe / gpt-4o-mini-tts) are REGIONAL; East US 2 is the default because it lists them.')
param location string = 'eastus2'

@minLength(2)
@maxLength(12)
@description('Required. Short, lowercase, alphanumeric base name used to derive all resource names.')
param baseName string = 'sekisho'

@description('Optional. Gateway container image. Defaults to a public placeholder; CI replaces it with the real Sekisho image.')
param containerImage string = 'mcr.microsoft.com/k8se/quickstart:latest'

@description('Optional. Chat completions model deployed on Foundry and used by the playground (CHAT_MODEL).')
param chatModel string = 'gpt-5.4'

@description('Optional. Additional Foundry model deployments (besides STT/TTS/chat). Each item: { name, format?, version?, skuName?, capacity? }.')
param additionalModelDeployments array = [
  { name: 'gpt-5.4-mini', format: 'OpenAI', version: '2026-03-17' }
  { name: 'gpt-5.3-codex', format: 'OpenAI', version: '2026-02-24' }
  { name: 'DeepSeek-V4-Pro', format: 'DeepSeek', version: '2026-04-23' }
]

// ===================== Entra Easy Auth (ADR 0003) — PREREQUISITES =====================
// An Entra app registration must be created OUT OF BAND (see README). Supply its values here.
@description('Required. Entra app registration (client) ID used by Container Apps Easy Auth.')
param aadClientId string

@description('Required. Entra app registration client secret. Surfaced only as an ACA secret; never hardcoded or committed.')
@secure()
param aadClientSecret string

@description('Optional. Entra tenant ID used to build the OpenID issuer. Defaults to the deployment tenant.')
param aadTenantId string = subscription().tenantId

@description('Optional. Explicit OpenID issuer URL override. If empty, it is derived from the cloud Entra login endpoint and aadTenantId (the v2.0 issuer).')
param openIdIssuer string = ''

@description('Optional. Tags applied to all resources.')
param tags object = {}

@description('Optional. Role definition GUID for "Cognitive Services User". Override for tenants (e.g. some MCAP/sandbox subscriptions) where this same-named role has a different GUID.')
param cognitiveServicesUserRoleId string = 'a97b65f3-24c7-4388-baec-2e87618995b6'

@description('Optional. Role definition GUID for "Key Vault Secrets Officer". Override for tenants where this same-named role has a different GUID.')
param keyVaultSecretsOfficerRoleId string = 'b86a8fe4-44ce-4948-aee7-ecce2b3f48c9'

// Deterministic short suffix for globally-unique-ish names.
var token = take(uniqueString(resourceGroup().id, baseName), 6)
var nameBase = toLower(baseName)

var foundryName = '${nameBase}-foundry-${token}'
var keyVaultName = take('kv${replace(nameBase, '-', '')}${token}', 24)
var environmentName = '${nameBase}-env-${token}'
var appName = '${nameBase}-gw-${token}'

// Derive the Entra v2.0 issuer from the active cloud's login endpoint (e.g. for AzureCloud:
// https://login.microsoftonline.com/<tenantId>/v2.0). environment() keeps this sovereign-cloud safe.
var effectiveIssuer = empty(openIdIssuer)
  ? '${environment().authentication.loginEndpoint}${aadTenantId}/v2.0'
  : openIdIssuer

// ---- Foundry account + audio model deployments (ADR 0001 + 0002) ----
module foundry 'modules/foundry.bicep' = {
  name: 'foundry'
  params: {
    name: foundryName
    location: location
    customSubDomainName: foundryName
    chatModelName: chatModel
    additionalDeployments: additionalModelDeployments
    tags: tags
  }
}

// ---- Key Vault Key store (ADR 0001) ----
module keyvault 'modules/keyvault.bicep' = {
  name: 'keyvault'
  params: {
    name: keyVaultName
    location: location
    tags: tags
  }
}

// ---- ACA gateway (ADR 0001 + 0003), consuming the Foundry base URL and the Key Vault URI ----
module aca 'modules/aca.bicep' = {
  name: 'aca'
  params: {
    name: appName
    environmentName: environmentName
    location: location
    containerImage: containerImage
    foundryBaseUrl: foundry.outputs.foundryOpenAiV1BaseUrl
    foundrySpeechBaseUrl: foundry.outputs.endpoint
    keyVaultUri: keyvault.outputs.vaultUri
    aadClientId: aadClientId
    aadClientSecret: aadClientSecret
    openIdIssuer: effectiveIssuer
    chatModel: chatModel
    tags: tags
  }
}

// ---- RBAC: grant the gateway managed identity its data-plane roles (ADR 0001) ----
// NOTE: this module references aca.outputs.appPrincipalId, which creates an IMPLICIT dependency on
// the ACA module. That guarantees the system-assigned principalId exists before the role
// assignments are created (no explicit dependsOn needed — it would be flagged as redundant).
module rbac 'modules/rbac.bicep' = {
  name: 'rbac'
  params: {
    principalId: aca.outputs.appPrincipalId
    foundryAccountName: foundry.outputs.accountName
    keyVaultName: keyvault.outputs.vaultName
    cognitiveServicesUserRoleId: cognitiveServicesUserRoleId
    keyVaultSecretsOfficerRoleId: keyVaultSecretsOfficerRoleId
  }
}

@description('Public FQDN of the Sekisho gateway (point OpenAI SDK base_url here).')
output gatewayFqdn string = aca.outputs.appFqdn

@description('Foundry account endpoint. The OpenAI v1 base is <foundryEndpoint>openai/v1/.')
output foundryEndpoint string = foundry.outputs.endpoint

@description('Key Vault URI backing the Sekisho Key store.')
output keyVaultUri string = keyvault.outputs.vaultUri
