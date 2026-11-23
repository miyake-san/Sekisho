# User Guide

Sekisho exposes **Microsoft Foundry** as a drop-in **OpenAI-compatible** endpoint. Any app that
accepts an OpenAI-style *base URL* + *API key* (e.g. the OpenAI SDKs, Obsidian Web Clipper, VS Code
extensions, Open WebUI) can talk to Foundry through Sekisho — no Foundry key required.

You need exactly two things:

| What | Value | Where to get it |
|------|-------|-----------------|
| **Base URL** | `https://<GATEWAY_FQDN>/openai/v1/` | The `gatewayFqdn` deployment output (see [deploy guide](deploy.md)) |
| **API key** | A **Sekisho Key** | The admin UI at `https://<GATEWAY_FQDN>/admin` |

> The "token" you paste into other apps is your **Sekisho Key**, *not* an Entra/Azure token.
> Sekisho swaps it for a managed-identity token to Foundry behind the scenes.

---

## 1. Get your Base URL

The base URL is the gateway FQDN with the OpenAI path:

```
https://<GATEWAY_FQDN>/openai/v1/
```

Find the FQDN from the deployment output:

```powershell
az deployment group show -g rg-sekisho -n main --query properties.outputs.gatewayFqdn.value -o tsv
```

Or from the Container App:

```powershell
az containerapp show -g rg-sekisho -n <APP_NAME> --query properties.configuration.ingress.fqdn -o tsv
```

---

## 2. Get your API key (Sekisho Key)

1. Open `https://<GATEWAY_FQDN>/admin` in a browser. You'll be redirected to Microsoft Entra
   sign-in (Easy Auth protects this page only).
2. Click **Create key**, give it a name (e.g. `obsidian`), and **copy the value immediately** —
   it is shown only once.
3. Use that value as the `api_key` / Bearer token in your client.

**Rotating / revoking:** the admin UI also lets you **rotate** a key (issues a new value while the
old one keeps working for a grace window) and **revoke** it (immediate). Rotate periodically and
use a separate key per app so you can revoke one without affecting the others.

---

## 3. Available models

| Capability | Model name to use |
|------------|-------------------|
| Chat / completions | `gpt-5.4` |
| Speech-to-text (transcription) | `gpt-4o-mini-transcribe` |
| Text-to-speech | `gpt-4o-mini-tts` |

---

## 4. Use it in common clients

### OpenAI Python SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://<GATEWAY_FQDN>/openai/v1/",
    api_key="<YOUR_SEKISHO_KEY>",
)

resp = client.chat.completions.create(
    model="gpt-5.4",
    messages=[{"role": "user", "content": "Hello from Sekisho!"}],
)
print(resp.choices[0].message.content)
```

### curl

```bash
curl "https://<GATEWAY_FQDN>/openai/v1/chat/completions" \
  -H "Authorization: Bearer <YOUR_SEKISHO_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-5.4","messages":[{"role":"user","content":"Say hi"}]}'
```

### Obsidian Web Clipper

Obsidian Web Clipper supports any OpenAI-compatible provider:

1. **Settings → Interpreter → Provider** → add/select a custom (OpenAI-compatible) provider.
2. **Base URL / Endpoint:** `https://<GATEWAY_FQDN>/openai/v1/`
   *(If the field expects the full path, use `https://<GATEWAY_FQDN>/openai/v1/chat/completions`.)*
3. **API key:** your **Sekisho Key**.
5. **Model:** `gpt-5.4`.
5. Save and run an interpret action on a clipped page to confirm it works.

### Generic OpenAI-compatible app

Set these wherever the app asks for an "OpenAI API" configuration:

| Field | Value |
|-------|-------|
| API base / Endpoint | `https://<GATEWAY_FQDN>/openai/v1/` |
| API key | `<YOUR_SEKISHO_KEY>` |
| Model | `gpt-5.4` (or an audio model) |

---

## 5. Audio (speech) examples

### Transcribe (speech-to-text)

```bash
curl "https://<GATEWAY_FQDN>/openai/v1/audio/transcriptions" \
  -H "Authorization: Bearer <YOUR_SEKISHO_KEY>" \
  -F "model=gpt-4o-mini-transcribe" \
  -F "file=@recording.webm"
```

### Speak (text-to-speech)

```bash
curl "https://<GATEWAY_FQDN>/openai/v1/audio/speech" \
  -H "Authorization: Bearer <YOUR_SEKISHO_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini-tts","input":"Hello there","voice":"alloy"}' \
  --output speech.mp3
```

### Azure Speech routes (mai-transcribe-1 / Azure STT) — for Pluely and other clients

Besides the OpenAI-compatible audio routes above, Sekisho exposes the **Azure Speech
(`cognitiveservices`) REST surface** under a separate path prefix: `/speech/...`. This lets you point
third-party tools (e.g. **Pluely**) at a distinct route variation while still authenticating with a
single Sekisho Key. Sekisho swaps your key for a managed-identity Entra token scoped to
`https://cognitiveservices.azure.com/.default`, so you never handle an Azure Speech key (the Foundry
account is keyless / `disableLocalAuth: true`).

| Capability | Route on Sekisho | Notes |
|---|---|---|
| OpenAI-compatible transcription | `POST /openai/v1/audio/transcriptions` | model `gpt-4o-mini-transcribe` |
| OpenAI-compatible TTS | `POST /openai/v1/audio/speech` | model `gpt-4o-mini-tts` |
| Azure fast/batch transcription (`mai-transcribe-1`) | `POST /speech/speechtotext/transcriptions:transcribe?api-version=2025-10-15` | Azure Speech REST; HTTP, proxied transparently |
| Azure Speech generic REST | `POST /speech/<azure-speech-path>` | any Speech REST path is forwarded to the Foundry account endpoint |

Fast transcription example (the `mai-transcribe-1` enhanced model):

```bash
curl "https://<GATEWAY_FQDN>/speech/speechtotext/transcriptions:transcribe?api-version=2025-10-15" \
  -H "Authorization: Bearer <YOUR_SEKISHO_KEY>" \
  -F 'definition={"locales":["en-US"],"enhancedMode":{"model":"mai-transcribe-1"}};type=application/json' \
  -F "audio=@recording.wav"
```

> **Realtime / continuous recognition (Speech SDK):** the Azure Speech SDK realtime modes
> (`mai-transcribe` realtime and standard Azure STT continuous recognition) use a **WebSocket**
> protocol, which cannot be transparently reverse-proxied by Sekisho's HTTP gateway with a simple
> header swap. Those modes are **not** exposed under `/speech/...` today. See the deploy runbook for
> the two options (a WebSocket relay, or a short-lived token endpoint so the SDK connects directly to
> Foundry). Batch/fast transcription via the REST route above covers most third-party integrations.

---

## 6. Built-in playground

A browser playground (chat + microphone transcription + speech) is available at:

```
https://<GATEWAY_FQDN>/playground
```

It's enabled when the app has a `PLAYGROUND_KEY` configured, and is handy for a quick smoke test
without wiring an external client.

---

## 7. Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| `401 Unauthorized` | Missing/invalid key. Confirm you copied the full Sekisho Key and send it as `Authorization: Bearer <key>`. |
| `404` on a request | Check the base URL ends with `/openai/v1/` and the model name is correct. |
| Garbled / empty response | Confirm the model name matches the deployed models (`gpt-5.4`, `gpt-4o-mini-transcribe`, `gpt-4o-mini-tts`). |
| Can't reach `/admin` | Easy Auth sign-in is required; ensure you're signing in with an account in the app's Entra tenant. |
| Key stopped working | It may have been **revoked** or rotated past its grace window — create or rotate a key in `/admin`. |