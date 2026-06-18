metadata name = 'Sekisho Foundry account + audio model deployments'
metadata description = 'Provisions the Microsoft Foundry (Cognitive Services "AIServices") account with a custom subdomain and key-auth disabled (Entra-only), plus the serialized STT/TTS audio model deployments. Implements ADR 0001 (managed-identity gateway) and ADR 0002 (audio STT/TTS).'

// =====================================================================================
// Foundry account (Microsoft.CognitiveServices/accounts, kind AIServices)
// ADR 0001: key auth is disabled by policy; callers reach Foundry only with Entra tokens,
//           which REQUIRES a custom subdomain. No Foundry API key is ever created/stored.
// =====================================================================================

@description('Required. Name of the Foundry (Cognitive Services AIServices) account.')
param name string

@description('Optional. Location. NOTE: the ADR 0002 audio models (gpt-4o-mini-transcribe / gpt-4o-mini-tts) are REGIONAL; East US 2 is a safe default that lists them.')
param location string = 'eastus2'

@description('Optional. Custom subdomain name. REQUIRED for Entra (AAD) token authentication; must be globally unique. Defaults to the lowercased account name.')
param customSubDomainName string = toLower(name)

@description('Optional. Cognitive Services account SKU name.')
param sku string = 'S0'

// ---- STT model (ADR 0002): speech-to-text ----
@description('Optional. STT (speech-to-text) model/deployment name.')
param sttModelName string = 'gpt-4o-mini-transcribe'

@description('Optional. STT model version. Leave empty to let Foundry pick the model default version (most robust); set to pin a specific version string.')
param sttModelVersion string = ''

@description('Optional. STT deployment SKU name (GlobalStandard or Standard, as offered in the region).')
param sttSkuName string = 'GlobalStandard'

@description('Optional. STT deployment capacity (capacity units; raise per your regional quota).')
param sttCapacity int = 300

// ---- TTS model (ADR 0002): text-to-speech ----
@description('Optional. TTS (text-to-speech) model/deployment name.')
param ttsModelName string = 'gpt-4o-mini-tts'

@description('Optional. TTS model version. Leave empty to let Foundry pick the model default version; set to pin a specific version string.')
param ttsModelVersion string = ''

@description('Optional. TTS deployment SKU name (GlobalStandard or Standard, as offered in the region).')
param ttsSkuName string = 'GlobalStandard'

@description('Optional. TTS deployment capacity (capacity units; raise per your regional quota).')
param ttsCapacity int = 300

// ---- Chat model: chat completions ----
@description('Optional. Chat (chat completions) model/deployment name.')
param chatModelName string = 'gpt-5.4'

@description('Optional. Chat model version. Leave empty to let Foundry pick the model default version; set to pin a specific version string.')
param chatModelVersion string = '2026-03-05'

@description('Optional. Chat deployment SKU name (GlobalStandard or Standard, as offered in the region).')
param chatSkuName string = 'GlobalStandard'

@description('Optional. Chat deployment capacity (capacity units; raise per your regional quota).')
param chatCapacity int = 350

@description('Optional. Additional model deployments to create after the chat model (serialized). Each item: { name: string, format?: string (default OpenAI), version?: string, skuName?: string (default GlobalStandard), capacity?: int (default 1) }.')
param additionalDeployments array = []

@description('Optional. Tags to apply to the account.')
param tags object = {}

@description('Optional. Foundry project name (child of the account). Defaults to the account name.')
param projectName string = name

@description('Optional. Foundry project display name.')
param projectDisplayName string = 'Sekisho'

// Build the model objects, including "version" only when explicitly provided.
var sttModel = empty(sttModelVersion)
  ? { name: sttModelName, format: 'OpenAI' }
  : { name: sttModelName, format: 'OpenAI', version: sttModelVersion }

var ttsModel = empty(ttsModelVersion)
  ? { name: ttsModelName, format: 'OpenAI' }
  : { name: ttsModelName, format: 'OpenAI', version: ttsModelVersion }

var chatModel = empty(chatModelVersion)
  ? { name: chatModelName, format: 'OpenAI' }
  : { name: chatModelName, format: 'OpenAI', version: chatModelVersion }

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: name
  location: location
  kind: 'AIServices'
  // System-assigned identity is REQUIRED for the new Foundry project resource model.
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: sku
  }
  properties: {
    allowProjectManagement: true // enables the new Foundry project resource (accounts/projects)
    customSubDomainName: customSubDomainName // REQUIRED for Entra token auth
    disableLocalAuth: true // MANDATORY: key auth disabled, Entra-only (ADR 0001)
    publicNetworkAccess: 'Enabled'
  }
  tags: tags
}

// STT deployment (created first).
resource sttDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: sttModelName
  sku: {
    name: sttSkuName
    capacity: sttCapacity
  }
  properties: {
    model: sttModel
  }
}

// TTS deployment. Deployments on a CognitiveServices account CANNOT be created in parallel,
// so this one is serialized behind the STT deployment via an explicit dependency.
resource ttsDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: ttsModelName
  sku: {
    name: ttsSkuName
    capacity: ttsCapacity
  }
  properties: {
    model: ttsModel
  }
  dependsOn: [
    sttDeployment
  ]
}

// Chat completions deployment. Deployments on a CognitiveServices account CANNOT be created in
// parallel, so this one is serialized behind the TTS deployment via an explicit dependency.
resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: chatModelName
  sku: {
    name: chatSkuName
    capacity: chatCapacity
  }
  properties: {
    model: chatModel
  }
  dependsOn: [
    ttsDeployment
  ]
}

// Additional model deployments (e.g. extra chat / codex / DeepSeek models). Serialized after the
// chat deployment AND among themselves via @batchSize(1), because CognitiveServices account
// deployments cannot be created in parallel. Each item: { name, format?, version?, skuName?, capacity? }.
@batchSize(1)
resource additionalModelDeployments 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = [
  for dep in additionalDeployments: {
    parent: account
    name: dep.name
    sku: {
      name: contains(dep, 'skuName') ? dep.skuName : 'GlobalStandard'
      capacity: contains(dep, 'capacity') ? dep.capacity : 1
    }
    properties: {
      model: (contains(dep, 'version') && !empty(dep.version))
        ? { name: dep.name, format: contains(dep, 'format') ? dep.format : 'OpenAI', version: dep.version }
        : { name: dep.name, format: contains(dep, 'format') ? dep.format : 'OpenAI' }
    }
    dependsOn: [
      chatDeployment
    ]
  }
]

// Foundry project (new Foundry resource model). Serialized after the model deployments so it does
// not race with the account-level deployment operations (which cannot run in parallel).
resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: projectName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: projectDisplayName
    description: 'Sekisho Foundry project.'
  }
  dependsOn: [
    chatDeployment
    additionalModelDeployments
  ]
}

@description('Resource ID of the Foundry account.')
output accountId string = account.id

@description('Name of the Foundry account.')
output accountName string = account.name

@description('Primary endpoint of the Foundry account (already ends with a trailing slash).')
output endpoint string = account.properties.endpoint

@description('Computed OpenAI v1 base URL for the gateway: <endpoint>openai/v1/.')
output foundryOpenAiV1BaseUrl string = '${account.properties.endpoint}openai/v1/'

@description('Names of the additional model deployments created.')
output additionalDeploymentNames array = [for dep in additionalDeployments: dep.name]

@description('Azure Speech (cognitiveservices) data-plane base URL. Speech models such as mai-transcribe-1 and standard STT are built into the AIServices account and are reached via this endpoint (not via accounts/deployments). Used by the gateway as FOUNDRY_SPEECH_BASE_URL.')
output speechEndpoint string = account.properties.endpoint

@description('Name of the chat completions model deployment.')
output chatDeploymentName string = chatDeployment.name

@description('Name of the Foundry project (new Foundry project resource).')
output projectName string = project.name

@description('Resource ID of the Foundry project.')
output projectId string = project.id
