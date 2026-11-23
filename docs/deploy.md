# Deploy Sekisho to Azure

This is the end-to-end runbook to deploy **Sekisho** — the managed-identity reverse-proxy
gateway that turns Entra-only **Microsoft Foundry** into a drop-in OpenAI-compatible endpoint.

The deployment provisions (all via the Bicep in [`infra/`](../infra/README.md)):

| Resource | Purpose |
|----------|---------|
| Microsoft Foundry account (`AIServices`) | Entra-only model endpoint + `gpt-5.4` (chat completions), `gpt-4o-mini-transcribe` (STT) and `gpt-4o-mini-tts` (TTS) deployments |
| Key Vault | Backs the Sekisho API-key store |
| Container Apps environment + app | Runs the gateway container (system-assigned managed identity, external ingress on 8000, Entra Easy Auth for `/admin`) |
| RBAC role assignments | Grants the gateway MI `Cognitive Services User` on Foundry and `Key Vault Secrets Officer` on the vault |
| Azure Container Registry (ACR) | Stores the Sekisho container image |

> **Architecture:** no Foundry API key exists anywhere. The gateway authenticates to Foundry with
> its **system-assigned managed identity**; inbound callers authenticate with a Sekisho **Key**.

---

## 1. Prerequisites

| Tool / requirement | Notes |
|--------------------|-------|
| **Azure CLI ≥ 2.70** | `az version` |
| **Bicep ≥ 0.33.93** | `az bicep version` (validated build) |
| **Docker** *(optional)* | Only for local image validation; the cloud build uses `az acr build` |
| **Azure subscription + region** | Use a region that lists the audio models — **`eastus2`** is the safe default (ADR 0002) |
| **Deployer RBAC** | `Owner`, **or** `Contributor` **+ `User Access Administrator`** on the resource group (the RBAC module creates role assignments) |
| **Entra app-registration rights** | Required to create the Easy Auth app registration (ADR 0003) |
| **Foundry model quota** | Quota for the two audio model deployments in the chosen region |

```powershell
az login
az account set --subscription "<your-subscription-id>"
```

Register the resource providers (first time in a subscription):

```powershell
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.CognitiveServices
az provider register --namespace Microsoft.KeyVault
az provider register --namespace Microsoft.ContainerRegistry
az provider register --namespace Microsoft.OperationalInsights
```

Set a few shell variables used throughout (PowerShell):

```powershell
$RG       = "rg-sekisho"
$LOCATION = "eastus2"
$BASENAME = "sekisho"            # 2-12 lowercase alphanumerics
$ACR      = "acrsekisho$(Get-Random -Maximum 99999)"   # must be globally unique, alphanumeric
$IMAGETAG = "v1"
```

---

## 2. Create the resource group

```powershell
az group create --name $RG --location $LOCATION
```

---

## 3. Build and push the container image (ACR)

`az acr build` builds the image **in the cloud** from the repo's [`Dockerfile`](../Dockerfile) —
no local Docker required.

```powershell
# Create a Basic ACR.
az acr create --resource-group $RG --name $ACR --sku Basic

# Build + push straight from the repo root (run from the project root).
az acr build --registry $ACR --image "sekisho:$IMAGETAG" .
```

The pushed image reference is `"$ACR.azurecr.io/sekisho:$IMAGETAG"`.

---

## 4. Create the Entra app registration (Easy Auth)

Easy Auth protects only the `/admin` surface. Create the registration before deploying.

```powershell
# Create the app registration.
$APP = az ad app create --display-name "sekisho-easyauth" --sign-in-audience AzureADMyOrg | ConvertFrom-Json
$AAD_CLIENT_ID = $APP.appId

# Create a client secret (copy the value; it is shown only once).
$SECRET = az ad app credential reset --id $AAD_CLIENT_ID --append --display-name "easyauth" --years 1 | ConvertFrom-Json
$env:AAD_CLIENT_SECRET = $SECRET.password

$AAD_TENANT_ID = (az account show --query tenantId -o tsv)
"clientId = $AAD_CLIENT_ID; tenantId = $AAD_TENANT_ID"
```

> If your tenant blocks app-registration via CLI, create it in the portal:
> **Microsoft Entra ID → App registrations → New registration**, then
> **Certificates & secrets → New client secret**. Copy the **Application (client) ID**,
> **Directory (tenant) ID**, and the secret **value**.
>
> The **Redirect URI** is wired in **step 6** once the gateway FQDN is known.

---

## 5. Deploy the infrastructure

Deploy the Bicep with the **ACR image** baked in. The Container App pulls it using its
system-assigned managed identity (`AcrPull` is granted in step 5b).

> **First-revision pull race:** the managed identity does not exist until the app is created,
> so the very first revision is deployed with the public **placeholder** image; step 5b then
> grants `AcrPull`, wires the registry, and switches to the real image. This avoids a
> chicken-and-egg failure and matches the "CI replaces the image" model in
> [`infra/README.md`](../infra/README.md).

### 5a. Provision (placeholder image)

```powershell
az deployment group create `
  --resource-group $RG `
  --template-file infra/main.bicep `
  --parameters infra/main.bicepparam `
  --parameters baseName=$BASENAME location=$LOCATION `
               aadClientId=$AAD_CLIENT_ID aadTenantId=$AAD_TENANT_ID
```

`aadClientSecret` flows from the `AAD_CLIENT_SECRET` environment variable via
[`main.bicepparam`](../infra/main.bicepparam).

Capture the outputs:

```powershell
$GATEWAY_FQDN = az deployment group show -g $RG -n main --query properties.outputs.gatewayFqdn.value -o tsv
$APP_NAME     = (az containerapp list -g $RG --query "[0].name" -o tsv)
"Gateway: https://$GATEWAY_FQDN"
```

### 5b. Grant ACR pull and switch to the real image

```powershell
# Object ID of the app's system-assigned managed identity.
$MI_PRINCIPAL = az containerapp show -g $RG -n $APP_NAME --query identity.principalId -o tsv
$ACR_ID       = az acr show -g $RG -n $ACR --query id -o tsv

# Grant AcrPull so the managed identity can pull from ACR.
az role assignment create --assignee-object-id $MI_PRINCIPAL --assignee-principal-type ServicePrincipal `
  --role AcrPull --scope $ACR_ID

# Wire the registry to the app (managed-identity auth) and roll to the real image.
az containerapp registry set -g $RG -n $APP_NAME --server "$ACR.azurecr.io" --identity system
az containerapp update     -g $RG -n $APP_NAME --image "$ACR.azurecr.io/sekisho:$IMAGETAG"
```

> Role propagation can take a minute. If the new revision fails to pull, wait ~60s and re-run the
> `az containerapp update` command.

---

## 6. Wire the Easy Auth redirect URI

Now that the FQDN is known, add the redirect URI to the Entra app registration:

```powershell
az ad app update --id $AAD_CLIENT_ID `
  --web-redirect-uris "https://$GATEWAY_FQDN/.auth/login/aad/callback"
```

---

## 7. Create your first Sekisho API key

Open the admin UI in a browser (you'll be redirected to Entra sign-in):

```
https://<GATEWAY_FQDN>/admin
```

Create a key (e.g. `default`) and **copy the value** — it is shown only once. This is the
`api_key` your OpenAI clients use. See the [User Guide](user-guide.md).

---

## 8. Verify

```powershell
# Health (no auth required).
curl "https://$GATEWAY_FQDN/health"      # -> {"status":"ok"}

# A real chat completion through the gateway (use a key from step 7).
curl "https://$GATEWAY_FQDN/openai/v1/chat/completions" `
  -H "Authorization: Bearer <YOUR_SEKISHO_KEY>" `
  -H "Content-Type: application/json" `
  -d '{"model":"gpt-5.4","messages":[{"role":"user","content":"Say hi"}]}'
```

The interactive **playground** (chat + speech) is at `https://<GATEWAY_FQDN>/playground` (enabled
when `PLAYGROUND_KEY` is configured on the app).

---

## Updating the app (new image)

```powershell
az acr build --registry $ACR --image "sekisho:v2" .
az containerapp update -g $RG -n $APP_NAME --image "$ACR.azurecr.io/sekisho:v2"
```

---

## Teardown

```powershell
az group delete --name $RG --yes --no-wait
# Optionally remove the Entra app registration.
az ad app delete --id $AAD_CLIENT_ID
```

The Key Vault has **soft delete** enabled. To reuse the same name within the retention window,
purge it first: `az keyvault purge --name <vaultName>`.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| New revision stuck / `ImagePullBackOff` | `AcrPull` not propagated yet — wait ~60s and re-run `az containerapp update`. |
| `/admin` returns a login loop | Redirect URI mismatch — confirm step 6 set `https://<FQDN>/.auth/login/aad/callback` exactly. |
| `401` from `/openai/*` | Missing/invalid Sekisho key. Create one at `/admin` and pass it as `Authorization: Bearer <key>`. |
| Audio models fail to deploy | The region doesn't list them or quota is exhausted — pick an audio-capable region (`eastus2`) and raise quota. |
| Deployment role-assignment error | The deployer needs `Owner` or `Contributor` + `User Access Administrator` on the RG. |

