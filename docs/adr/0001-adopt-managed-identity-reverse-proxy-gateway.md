---
status: proposed
date: 2026-06-16
decision-makers: Diogo Miyake (owner)
---

# Adopt a managed-identity reverse-proxy gateway for Foundry data-plane access (Sekisho v1)

## Context and Problem Statement

We need a single OpenAI/Ollama-compatible endpoint that lets any existing OpenAI-SDK
application consume **Microsoft Foundry** models (OpenAI-family and Microsoft AI "MAI"
models) without each app having to handle Microsoft Entra ID / managed-identity auth.

Two hard facts force the design:

1. **The Foundry resource has key auth disabled.** An Azure admin policy
   ("Foundry Tools resources should have key access disabled") sets `disableLocalAuth: true`
   on the `Microsoft.CognitiveServices/accounts` resource. Callers therefore **cannot** talk
   to Foundry directly with an API key — only Microsoft Entra ID tokens are accepted.
2. **Foundry already speaks OpenAI v1.** Foundry exposes an OpenAI-compatible endpoint at
   `https://<resource>.openai.azure.com/openai/v1/` (equivalently `…services.ai.azure.com/openai/v1/`).
   `api-version` is no longer required, `model` is the deployment name, and the same surface
   serves OpenAI, MAI, DeepSeek, and Grok models.

So we want a thin service ("the **Gateway**") that callers authenticate to with a simple
bearer credential ("a **Key**"), which then forwards their request to Foundry using a
managed identity — turning "Entra-only Foundry" into "drop-in OpenAI endpoint."

The central design question was *how* the Gateway talks to Foundry: forward the raw HTTP
request (reverse proxy), or parse each request into typed models and re-issue it via an
Azure SDK (re-origination). The "no key auth" constraint does **not** decide this — both
approaches authenticate to Foundry with a managed identity; the policy is orthogonal to
payload handling.

Project name: **Sekisho** (関所) — a historical checkpoint where travelers presented a pass
to proceed; here, callers present a Key to pass through to Foundry.

## Decision

Build **Sekisho v1** as an Azure Container Apps–hosted **reverse-proxy gateway**:

- **Caller auth (inbound).** Callers present a named, individually-rotatable **Key** as a
  bearer credential. Multiple Keys are supported; each can be created, rotated (with a grace
  window where old and new are both valid), and revoked independently. An off-by-default
  **Anonymous Mode** disables Key checks entirely (Ollama-style), enabled only by explicit
  configuration.
- **Foundry auth (outbound).** The Gateway authenticates to Foundry with a **managed
  identity** — it acquires an Entra token for scope `https://ai.azure.com/.default`, caches
  and refreshes it, and sets `Authorization: Bearer <token>` on the forwarded request. No
  Foundry API key is ever used or stored.
- **Payload handling: transparent reverse proxy (passthrough).** The Gateway forwards the
  caller's request body **unmodified** to `…/openai/v1/…`, swapping only the auth header and
  rewriting the target host/path. Streaming (SSE) passes through byte-for-byte. The Gateway
  does **not** parse, model, or re-serialize inference payloads.

**Scope (in):** the backend Gateway (proxy + Key auth + anonymous mode) and its Bicep
infrastructure.

**Non-goals (out, v1):**
- Control-plane CRUD over Foundry Routines / Workflows / Agents / Models (deferred to v2).
- Any inspection or transformation of inference content (content filtering, prompt
  rewriting, semantic caching, body-based routing). Choosing these later would justify
  re-originating payloads via an SDK and would supersede this ADR.
- The management frontend for Keys (Entra-protected; a thin UI over the Key store) — planned,
  but after the backend and infra land.

## Consequences

- Good, because any OpenAI-SDK client works unchanged by pointing `base_url` at the Gateway
  and using a Key as `api_key`; Entra complexity is hidden.
- Good, because new OpenAI params and endpoints (e.g. `/responses`, future fields) work with
  zero Gateway code changes — there are no payload models to keep in sync.
- Good, because the managed-identity-only path is the secure, policy-compliant design by
  construction; no secret ever grants Foundry access.
- Bad, because the Gateway is "dumb" to content — any v1 feature needing to read/modify the
  body is impossible without revisiting this decision.
- Bad, because streaming passthrough and token-refresh edge cases (expiry mid-stream,
  upstream 401 after rotation) must be handled carefully in the proxy layer.
- Follow-ups: provision Foundry with a custom subdomain; assign RBAC to the Gateway's
  managed identity; stand up Key Vault and the Key store; add the Entra-protected frontend
  (separate task/ADR); define the consumer "connection profile" (URL + Key bundle) handed to
  client apps.

## Implementation Plan

- **Affected paths** (greenfield — create):
  - `personal-foundry-connection/src/sekisho/main.py` — FastAPI app, route wiring, health.
  - `personal-foundry-connection/src/sekisho/proxy.py` — httpx streaming reverse proxy;
    forwards body unmodified to Foundry, rewrites host/path, swaps auth header,
    re-streams response (incl. SSE) to the caller.
  - `personal-foundry-connection/src/sekisho/auth.py` — inbound Key validation + Anonymous
    Mode toggle (FastAPI dependency).
  - `personal-foundry-connection/src/sekisho/foundry_token.py` — azure-identity bearer-token
    provider for scope `https://ai.azure.com/.default`, with caching/refresh.
  - `personal-foundry-connection/src/sekisho/keys.py` — Key Vault–backed Key store
    (list / validate / create / rotate-with-grace / revoke). No secrets held in process.
  - `personal-foundry-connection/src/sekisho/config.py` — pydantic-settings configuration.
  - `personal-foundry-connection/infra/main.bicep` + `infra/modules/`:
    `foundry.bicep` (`Microsoft.CognitiveServices/accounts`, kind AIServices, **custom
    subdomain**, `disableLocalAuth: true`), `aca.bicep` (Container App + environment +
    **system-assigned managed identity**, external ingress), `keyvault.bicep`,
    `rbac.bicep` (role assignments to the ACA managed identity).
  - `personal-foundry-connection/pyproject.toml` — deps + Python pin.
  - `personal-foundry-connection/tests/` — proxy, auth, and token tests.
- **Dependencies**: `fastapi`, `uvicorn[standard]`, `httpx`, `azure-identity`,
  `azure-keyvault-secrets`, `pydantic`, `pydantic-settings`. Python **3.14.x** (pin exactly;
  ">3.14" is not a real range yet).
- **RBAC / config required**:
  - ACA managed identity → **Cognitive Services User** (Foundry "Azure AI User") on the
    Foundry resource scope.
  - ACA managed identity → **Key Vault Secrets Officer** (rotate/create) on the vault.
  - Env: `FOUNDRY_BASE_URL` (`https://<resource>.openai.azure.com/openai/v1/`),
    `FOUNDRY_TOKEN_SCOPE=https://ai.azure.com/.default`, `ANONYMOUS_MODE=false`,
    `KEY_VAULT_URI`.
- **Patterns to follow**: keep Pydantic strictly on the Gateway's own control surface (Key
  CRUD, config) — never on inference payloads; acquire the Foundry token via a cached
  provider; stream upstream→downstream with httpx + a streaming response.
- **Patterns to avoid**: do **not** use `AzureOpenAI()` / `azure-ai-inference` to
  re-originate inference calls; do **not** use a Foundry API key; do **not** target a
  regional (non-custom-subdomain) endpoint; do **not** store Keys in code or plain ACA env;
  do **not** let a client Key authorize Key management (admin auth is separate, Entra-based).

### Verification

- [ ] An unmodified OpenAI Python client with `base_url=<gateway>/…` + a valid Key returns a
      completion from a Foundry deployment.
- [ ] A request with `stream=true` streams tokens through the Gateway as SSE with no buffering
      of the full body.
- [ ] A request carrying an OpenAI field the Gateway has never seen is forwarded and succeeds
      (proves no payload modeling).
- [ ] No Foundry **API key** appears anywhere in code, config, Key Vault, or ACA secrets; the
      Gateway calls Foundry only with an Entra token for `https://ai.azure.com/.default`.
- [ ] A request with a missing/invalid Key is rejected `401` when `ANONYMOUS_MODE=false`, and
      allowed when `ANONYMOUS_MODE=true`.
- [ ] Rotating a Key keeps the previous value valid during the grace window, then rejects it
      afterward; revoking a Key rejects it immediately without affecting other Keys.
- [ ] `az deployment` provisions a Foundry resource with a custom subdomain and
      `disableLocalAuth: true`, an ACA app with a system-assigned identity, and the two role
      assignments above.

## Alternatives Considered

- **SDK re-origination (Option B)**: parse each request into Pydantic models, call an Azure
  SDK, re-serialize to OpenAI JSON. Rejected for v1: perpetually chases OpenAI/Azure API
  drift, needs hand-written mappings per endpoint and manual SSE re-emission, and buys nothing
  unless we must inspect/transform bodies — which is an explicit non-goal. (The cited "no key
  auth" policy does not favor B; both options use managed identity to Foundry.)
- **Direct client→Foundry with Entra tokens (no Gateway)**: rejected — Foundry has key auth
  disabled and requires Entra tokens + custom subdomain + RBAC, which is exactly the
  complexity we want to hide from consumers; also no place to issue/rotate per-consumer Keys.
- **Azure API Management as the gateway**: viable and policy-rich, but heavier to operate for
  a personal/demo POC and overkill for v1; revisit if enterprise policy/quotas are needed.

## More Information

- Validated against Microsoft Learn (2026-06-16): Foundry OpenAI v1 endpoint and Entra scope
  `https://ai.azure.com/.default`; `disableLocalAuth`; custom-subdomain requirement for token
  auth; **Cognitive Services User** role; MAI models served on the same v1 surface.
- Glossary: `personal-foundry-connection/CONTEXT.md` (Foundry, Gateway, Key, Rotation,
  Anonymous Mode).
- Revisit this ADR if: a v1 requirement to inspect/transform inference content appears (→
  Option B / SDK), or enterprise needs (quotas, rich policy, multi-tenant governance) push
  toward API Management.
