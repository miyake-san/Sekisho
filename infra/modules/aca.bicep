metadata name = 'Sekisho gateway — Azure Container Apps (environment + app + Easy Auth)'
metadata description = 'Container Apps managed environment and the Sekisho gateway Container App: system-assigned managed identity, external ingress on 8000, gateway env wiring, and Container Apps built-in authentication (Easy Auth) with Microsoft Entra. Implements ADR 0001 and ADR 0003.'

@description('Required. Name of the gateway Container App.')
param name string

@description('Required. Name of the Container Apps managed environment.')
param environmentName string

@description('Optional. Location for the environment and app.')
param location string = resourceGroup().location

@description('Optional. Gateway container image. Defaults to a public placeholder; CI replaces it with the real Sekisho image.')
param containerImage string = 'mcr.microsoft.com/k8se/quickstart:latest'

@description('Required. Foundry OpenAI v1 base URL (from the foundry module): FOUNDRY_BASE_URL.')
param foundryBaseUrl string

@description('Required. Key Vault URI (from the keyvault module): KEY_VAULT_URI.')
param keyVaultUri string

@description('Optional. Entra token scope the gateway uses to call Foundry.')
param foundryTokenScope string = 'https://ai.azure.com/.default'
@description('Optional. Azure Speech (cognitiveservices) data-plane base URL: FOUNDRY_SPEECH_BASE_URL. Defaults to the Foundry account endpoint.')
param foundrySpeechBaseUrl string = ''

@description('Optional. Anonymous mode toggle for inbound Key checks. Off by default (ADR 0001).')
param anonymousMode string = 'false'

@description('Optional. Chat completions model/deployment name surfaced to the playground (CHAT_MODEL).')
param chatModel string = 'gpt-5.4'

// ---- Entra Easy Auth (ADR 0003). The app registration is a PREREQUISITE created out-of-band. ----
@description('Required. Entra app registration (client) ID used by Container Apps Easy Auth.')
param aadClientId string

@description('Required. Entra app registration client secret. Stored as an ACA secret (never hardcoded).')
@secure()
param aadClientSecret string

@description('Required. OpenID issuer URL for the Entra tenant (the v2.0 issuer endpoint).')
param openIdIssuer string

@description('Optional. Minimum replica count (ADR 0001 keeps at least one warm for token caching).')
param minReplicas int = 1

@description('Optional. Maximum replica count.')
param maxReplicas int = 3

@description('Optional. Container ingress target port.')
param targetPort int = 8000

@description('Optional. Tags to apply to the environment and app.')
param tags object = {}

// Name of the ACA secret that holds the Entra client secret, referenced by Easy Auth below.
var aadClientSecretName = 'aad-client-secret'

// Container Apps managed environment (Consumption-only; no VNet, so not zone-redundant).
resource managedEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    zoneRedundant: false
  }
}

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: tags
  // SYSTEM-ASSIGNED managed identity -> used to call Foundry & Key Vault (roles granted in rbac.bicep).
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: managedEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      // External ingress, target port 8000, auto transport, TLS required (no insecure).
      ingress: {
        external: true
        targetPort: targetPort
        transport: 'auto'
        allowInsecure: false
      }
      // The Entra client secret is surfaced ONLY as an ACA secret; Easy Auth references it by name.
      secrets: [
        {
          name: aadClientSecretName
          value: aadClientSecret
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'sekisho'
          image: containerImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'FOUNDRY_BASE_URL'
              value: foundryBaseUrl
            }
            {
              name: 'FOUNDRY_TOKEN_SCOPE'
              value: foundryTokenScope
            }
            {
              name: 'FOUNDRY_SPEECH_BASE_URL'
              value: foundrySpeechBaseUrl
            }
            {
              name: 'ANONYMOUS_MODE'
              value: anonymousMode
            }
            {
              name: 'KEY_VAULT_URI'
              value: keyVaultUri
            }
            {
              name: 'CHAT_MODEL'
              value: chatModel
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
}

// ============================ Easy Auth (ADR 0003) ============================
// The Microsoft.App/containerApps/authConfigs child MUST be named 'current'.
//
// CONTRACT — globalValidation.unauthenticatedClientAction = 'AllowAnonymous' (DO NOT force login
// globally). The Sekisho gateway API (/openai/*) and the playground MUST stay reachable WITHOUT an
// interactive browser login: API callers authenticate with a Sekisho *Key* (ADR 0001), not Entra.
// The application itself enforces /admin/* by detecting the absence of an Easy Auth principal and
// redirecting the browser to the Easy Auth login endpoint (/.auth/login/aad). Setting this to a
// global "RedirectToLoginPage" here would break the API and the playground, so it MUST remain
// 'AllowAnonymous'.
// ============================================================================
resource authConfig 'Microsoft.App/containerApps/authConfigs@2024-03-01' = {
  parent: app
  name: 'current'
  properties: {
    platform: {
      enabled: true
    }
    globalValidation: {
      unauthenticatedClientAction: 'AllowAnonymous'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: aadClientId
          clientSecretSettingName: aadClientSecretName
          openIdIssuer: openIdIssuer
        }
      }
    }
    login: {
      preserveUrlFragmentsForLogins: false
    }
  }
}

@description('Name of the gateway Container App.')
output appName string = app.name

@description('Public FQDN of the gateway Container App.')
output appFqdn string = app.properties.configuration.ingress.fqdn

@description('Principal (object) ID of the system-assigned managed identity of the app.')
output appPrincipalId string = app.identity.principalId
