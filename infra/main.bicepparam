using './main.bicep'

// Short, lowercase base name used to derive all resource names.
param baseName = 'sekisho'

// Region for all resources. Keep an audio-capable region for the ADR 0002 STT/TTS models
// (East US 2 lists gpt-4o-mini-transcribe / gpt-4o-mini-tts).
param location = 'eastus2'

// Gateway image. Placeholder until CI pushes the real Sekisho image.
param containerImage = 'mcr.microsoft.com/k8se/quickstart:latest'

// ===================== Entra Easy Auth prerequisites (ADR 0003) =====================
// Create an Entra app registration out of band (see README) and fill in its identifiers.

// Application (client) ID of the Entra app registration that fronts Easy Auth.
param aadClientId = '00000000-0000-0000-0000-000000000000'

// Client secret of that app registration.
// NEVER commit a real secret. It is read from the AAD_CLIENT_SECRET environment variable at
// build/deploy time (empty default keeps `az bicep build-params` happy when it is unset).
param aadClientSecret = readEnvironmentVariable('AAD_CLIENT_SECRET', '')

// Tenant ID used to derive the OpenID issuer (defaults to the deployment tenant if omitted).
param aadTenantId = '11111111-1111-1111-1111-111111111111'

// Optional: set an explicit issuer to override the derived value.
// param openIdIssuer = 'https://login.microsoftonline.com/<tenantId>/v2.0'

// Built-in role GUIDs. Defaults (in main.bicep) are the canonical Azure values and work in most
// subscriptions. Some MCAP/sandbox tenants expose the SAME-named roles under DIFFERENT GUIDs — if
// the `rbac` module fails with "RoleDefinitionDoesNotExist", look them up and override here:
//   az role definition list --name "Cognitive Services User"  --query "[].name" -o tsv
//   az role definition list --name "Key Vault Secrets Officer" --query "[].name" -o tsv
// Known overrides for the MCAP tenant family (e.g. 1a828a01-...):
// param cognitiveServicesUserRoleId  = 'a97b65f3-24c7-4388-baec-2e87135dc908'
// param keyVaultSecretsOfficerRoleId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
