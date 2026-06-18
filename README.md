# Sekisho（関所）

**Managed-identity reverse-proxy gateway that turns Entra-only Microsoft Foundry into a drop-in OpenAI-compatible endpoint.**

Ps.: It is not a product just an experiment, don't use in production. s

## Why "Sekisho"?

A **sekisho** (関所) was a *checkpoint barrier* on the great roads of feudal Japan — stations
like those along the Tōkaidō where the shogunate **inspected every traveler and every load of
goods** and decided who was allowed to pass. Nothing crossed without being checked.

That is exactly what this project does: it sits in front of Microsoft Foundry as a **checkpoint**.
Every request is inspected and authenticated (with a Sekisho **Key**) before it is allowed through,
and the gateway itself crosses the barrier to Foundry using its **managed identity** — so no Foundry
API key ever exists on either side. The name captures the role: a guarded gate that controls passage.

## What it is

Sekisho is a thin, stateless reverse proxy that lets any **OpenAI-compatible** client (OpenAI SDKs,
Obsidian Web Clipper, Open WebUI, VS Code extensions, …) talk to **Microsoft Foundry** — which is
**Entra-only** (key auth disabled) — without handling Entra tokens themselves.

- **Inbound:** callers authenticate with a **Sekisho Key** (`Authorization: Bearer <key>`).
- **Outbound:** the gateway calls Foundry with its **system-assigned managed identity** (Entra token,
  scope `https://ai.azure.com/.default`). **No Foundry API key exists anywhere.**
- **Key store:** Sekisho Keys are issued, rotated, and revoked from `/admin`, backed by **Key Vault**.

```
client ──Bearer <Sekisho Key>──►  Sekisho  ──Managed Identity (Entra)──►  Microsoft Foundry
                                  (関所)                                   (gpt-5.4 / STT / TTS)
```

## Features

- 🔑 **OpenAI-compatible** proxy at `/openai/v1/*` (chat, responses, audio STT/TTS).
- 🛡️ **Inbound Key auth** with constant-time comparison, rotation (grace window) and revocation.
- 🪪 **Managed-identity** outbound auth to Foundry — zero stored model credentials.
- 🔁 Automatic **401 → token refresh → retry** against Foundry.
- 🧪 Built-in **playground** (`/playground`) and **admin UI** (`/admin`, protected by Entra Easy Auth).
- 🎙️ Foundry **audio** models (speech-to-text / text-to-speech) exposed through the same endpoint.

## Models

| Capability | Deployment |
|------------|-----------|
| Chat / completions | `gpt-5.4` |
| Speech-to-text | `gpt-4o-mini-transcribe` |
| Text-to-speech | `gpt-4o-mini-tts` |

## Documentation

- **[docs/deploy.md](docs/deploy.md)** — end-to-end deployment runbook (Bicep + ACR + Entra + ACA).
- **[docs/user-guide.md](docs/user-guide.md)** — get your Base URL + Key and wire up OpenAI clients / Obsidian.
- **[infra/README.md](infra/README.md)** — infrastructure-as-code reference.
- **[docs/adr/](docs/adr/)** — architecture decision records.

## Repository layout

| Path | Purpose |
|------|---------|
| `src/sekisho/` | FastAPI app: `proxy`, `auth`, `keys`, `foundry_token`, `config`, and the `web/` UI |
| `infra/` | Bicep modules (Foundry + project, Key Vault, Container Apps, RBAC) |
| `docs/` | Deploy guide, user guide, ADRs |
| `tests/` | Pytest suite (proxy, auth, keys, token, web) |
| `scripts/` | Operational scripts (e.g. Easy Auth secret rotation) |
| `Dockerfile` | Multi-stage uv build (non-root, port 8000) |

## Develop & test

```bash
uv sync --all-groups        # install deps (Python 3.14)
uv run pytest -q            # run the test suite
uv run ruff check .         # lint
uv run mypy                 # type-check
uv run uvicorn sekisho.main:app --reload   # run locally (set FOUNDRY_BASE_URL)
```

## Operations

- **Easy Auth secret rotation:** the Entra client secret protecting `/admin` is policy-limited to a
  short lifetime in some tenants. Rotate it with
  [`scripts/rotate-easyauth-secret.ps1`](scripts/rotate-easyauth-secret.ps1).

## Security notes

- Foundry is **Entra-only** (`disableLocalAuth: true`) with a custom subdomain; the gateway is the
  only path in.
- The gateway managed identity holds least-privilege roles: **Cognitive Services User** on Foundry
  and **Key Vault Secrets Officer** on the vault — nothing else.
- `/admin` is protected by **Container Apps Easy Auth (Microsoft Entra)**; the API and playground stay
  reachable anonymously and are gated by the Sekisho **Key** instead.
