# Sekisho — Infrastructure (Bicep)

Infrastructure-as-Code for **Sekisho**, the managed-identity reverse-proxy gateway that turns
Entra-only **Microsoft Foundry** into a drop-in OpenAI-compatible endpoint.

Implements ADRs:

- `0001` — managed-identity reverse-proxy gateway (Foundry + Key Vault + ACA + RBAC).
- `0002` — Foundry audio models (STT/TTS) deployed on the Foundry account.
- `0003` — lightweight HTMX/FastAPI frontend with **Container Apps Easy Auth** for `/admin/*`.

## File layout

| File | Purpose |
|------|---------|
| `main.bicep` | Orchestrator (resource-group scope). Wires the modules and passes outputs between them. |
| `main.bicepparam` | Example parameter file (placeholders; secret read from an env var). |
| `modules/foundry.bicep` | Foundry account (`Microsoft.CognitiveServices/accounts`, kind `AIServices`) — custom subdomain, `disableLocalAuth: true`, plus the serialized `gpt-4o-mini-transcribe` (STT) and `gpt-4o-mini-tts` (TTS) deployments. |
| `modules/keyvault.bicep` | RBAC-authorized, soft-delete-enabled Key Vault that backs the Key store. |
| `modules/aca.bicep` | Container Apps environment + the gateway app (system-assigned identity, external ingress on 8000) + Easy Auth (`authConfigs/current`). |
| `modules/rbac.bicep` | Role assignments to the gateway managed identity: **Cognitive Services User** on Foundry, **Key Vault Secrets Officer** on the vault. |

> **Implementation note.** The modules use **native Bicep resource declarations** (not AVM registry
> modules). This was a deliberate choice: it compiles cleanly on the installed Bicep (validated with
> **0.33.93**) with **no registry restore**, and it maps 1:1 to the exact ADR-mandated properties
> (custom subdomain, `disableLocalAuth`, serialized deployments, the Easy Auth contract, and
> precisely-scoped RBAC). No external module download is required to build or deploy.

## Prerequisites

1. **Azure CLI + Bicep** (`az bicep version`). Validated with Bicep 0.33.93.
2. **An Azure subscription + resource group**, in a region that offers the ADR 0002 audio models.
3. **Deployer permissions:** `Owner` *or* `Contributor` **+ `User Access Administrator`** on the
   target resource group — `rbac.bicep` creates role assignments, which requires write access to
   `Microsoft.Authorization/roleAssignments`.
4. **An Entra app registration created out-of-band** (for Easy Auth — see below).
5. Quota for the two audio model deployments in the chosen region (raise capacity as needed).

### Entra app registration (Easy Auth prerequisite — ADR 0003)

Easy Auth protects only the admin surface; create the registration before (or update it right
after) the first deploy:

1. **Microsoft Entra ID → App registrations → New registration.** Single tenant is fine.
2. **Certificates & secrets → New client secret.** Copy the secret **value** — this is `aadClientSecret`.
3. Copy the **Application (client) ID** — this is `aadClientId` — and the **Directory (tenant) ID**
   — this is `aadTenantId`.
4. **Authentication → Add a platform → Web → Redirect URI:**
   `https://<gatewayFqdn>/.auth/login/aad/callback`
   The `gatewayFqdn` is a deployment **output**, so it is a chicken-and-egg: deploy once, read the
   `gatewayFqdn` output, then add the redirect URI (and re-run if you want it wired immediately).

## Parameters an operator must supply

| Parameter | Required? | Default | Notes |
|-----------|-----------|---------|-------|
| `aadClientId` | **Yes** | — | Entra app registration (client) ID for Easy Auth. |
| `aadClientSecret` | **Yes** (`@secure`) | — | Entra client secret. **Never commit it.** The example param reads it from the `AAD_CLIENT_SECRET` environment variable. Surfaced only as an ACA secret. |
| `aadTenantId` | No | deployment tenant | Used to derive the OpenID issuer. |
| `openIdIssuer` | No | derived | Override the derived `…/<tenantId>/v2.0` issuer if needed. |
| `baseName` | No | `sekisho` | 2–12 lowercase alphanumerics; seeds all resource names. |
| `location` | No | `eastus2` | **Must list the audio models** (see regional note). |
| `containerImage` | No | `mcr.microsoft.com/k8se/quickstart:latest` | Placeholder; CI replaces with the real Sekisho image. |
| `tags` | No | `{}` | Tags applied to all resources. |

## Deploy

```powershell
# 1) Resource group in an audio-capable region.
az group create --name rg-sekisho --location eastus2

# 2) Provide the Entra client secret via an environment variable (never commit it).
$env:AAD_CLIENT_SECRET = '<your-entra-client-secret>'

# 3) Deploy. The bicepparam supplies placeholders; override the real Entra IDs inline.
az deployment group create `
  --resource-group rg-sekisho `
  --template-file main.bicep `
  --parameters main.bicepparam `
  --parameters aadClientId=<app-client-id> aadTenantId=<tenant-id>
```

`aadClientSecret` flows from `AAD_CLIENT_SECRET` through `main.bicepparam`
(`readEnvironmentVariable('AAD_CLIENT_SECRET', '')`). To pass it explicitly instead:
`--parameters aadClientSecret=$env:AAD_CLIENT_SECRET`.

Validate without deploying:

```powershell
az bicep build --file main.bicep --stdout > $null   # compile (exit 0 == clean)
az deployment group what-if --resource-group rg-sekisho `
  --template-file main.bicep --parameters main.bicepparam `
  --parameters aadClientId=<app-client-id>
```

### Outputs

- `gatewayFqdn` — public FQDN of the gateway. Point an OpenAI SDK `base_url` at
  `https://<gatewayFqdn>/openai/v1/` and use a Sekisho **Key** as the `api_key`.
- `foundryEndpoint` — Foundry account endpoint (OpenAI v1 base = `<foundryEndpoint>openai/v1/`).
- `keyVaultUri` — Key Vault backing the Key store.

## Regional note (ADR 0002 — audio models)

The audio models `gpt-4o-mini-transcribe` (STT) and `gpt-4o-mini-tts` (TTS) are **regional**, so the
Foundry account is pinned to a region that lists them. **`location` defaults to `eastus2`** because
East US 2 reliably offers these audio models (and is the documented safe default). If you change the
region, confirm both models are available there first, and adjust `sttSkuName`/`ttsSkuName`
(`GlobalStandard` vs `Standard`) and the capacities to match the region's offering and your quota.

Model **versions** default to empty, which lets Foundry select each model's default version (the most
robust choice). Pin a specific version by setting `sttModelVersion` / `ttsModelVersion` on the
`foundry` module if you need a fixed version.

## Entra / auth contract (ADR 0001 + 0003)

- **Foundry is Entra-only.** `disableLocalAuth: true` and a **custom subdomain** are mandatory; the
  gateway calls Foundry with its **system-assigned managed identity** (token scope
  `https://ai.azure.com/.default`). **No Foundry API key exists anywhere** in this stack.
- **The gateway managed identity** gets `Cognitive Services User` on Foundry and
  `Key Vault Secrets Officer` on the vault — nothing else.
- **Easy Auth uses `unauthenticatedClientAction = 'AllowAnonymous'` on purpose.** The gateway API
  (`/openai/*`) and the playground must stay reachable **without** an interactive browser login —
  API clients authenticate with a Sekisho **Key**, not Entra. The application enforces `/admin/*`
  itself by redirecting unauthenticated browsers to `/.auth/login/aad`. Do **not** switch this to a
  global `RedirectToLoginPage`, or the API and playground break. (See the comment in `aca.bicep`.)

## Teardown

```powershell
az group delete --name rg-sekisho --yes --no-wait
```

The Key Vault has **soft delete** enabled (purge protection is **off** by default for easy POC
teardown). If you re-deploy with the same name within the retention window, recover or purge the
soft-deleted vault first (`az keyvault purge --name <vaultName>`). Turn purge protection **on** for
production by setting `enablePurgeProtection: true` on the `keyvault` module.