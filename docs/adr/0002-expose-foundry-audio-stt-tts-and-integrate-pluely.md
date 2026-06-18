---
status: proposed
date: 2026-06-16
decision-makers: Diogo Miyake (owner)
---

# Expose Foundry audio models (STT/TTS) through the gateway and integrate Personal Meeting Assistant (Sekisho)

## Context and Problem Statement

We need speech-to-text (voice input) and text-to-speech for clients of the **Sekisho**
gateway. The first concrete consumer is **Personal Meeting Assistant** — a lightweight desktop AI overlay
(Tauri/Rust, OpenAI-compatible) that captures audio and sends it to a configurable STT
provider via a cURL template with `{{AUDIO}}`, `{{API_KEY}}`, and `{{LANGUAGE}}` variables.

The important finding: **Foundry's audio models are OpenAI-compatible** and live on the same
`/openai/v1/audio/*` surface (`/audio/transcriptions`, `/audio/translations`,
`/audio/speech`) that ADR `0001` already proxies. Authentication (managed identity, scope
`https://ai.azure.com/.default`, `Cognitive Services User` role) and the `disableLocalAuth`
constraint are already handled by Sekisho. Therefore audio is a **feature on the existing
`/openai/*` route**, not a new gateway mechanism. This ADR records the model choices, the
route reuse, and the Personal Meeting Assistant integration — and explicitly scopes out the heavier audio paths.

Validated against Microsoft Learn (2026-06-16): Foundry "Models sold by Azure" audio models;
`/audio` API; 25 MB synchronous file limit; regional availability; content filtering not
applied to Whisper.

## Decision

- **Deploy these Foundry audio models (start):**
  - STT: **`gpt-4o-mini-transcribe`** (chosen for accuracy/latency/cost on voice + meeting
    capture). Fallback **`whisper`** for maximum OpenAI-client compatibility;
    `gpt-4o-transcribe-diarize` only if speaker labels are needed.
  - TTS: **`gpt-4o-mini-tts`** (steerable voice style/tone). Fallback **`tts`** (speed) /
    **`tts-hd`** (quality).
- **Expose via the existing Sekisho `/openai/*` passthrough route** — no new route type.
  Clients call `…/openai/v1/audio/transcriptions`, `…/audio/translations`, and
  `…/audio/speech`. Sekisho validates the caller **Key**, swaps in the managed-identity
  bearer token (scope `https://ai.azure.com/.default`), and forwards unmodified.
- **Integrate Personal Meeting Assistant** via its **Custom STT Provider (cURL)** pointed at Sekisho with a Key
  as `{{API_KEY}}` (a Sekisho Key, never a Foundry key).

**Non-goals (this ADR):**
- Real-time speech-to-speech (GPT-4o **realtime** API over WebSocket) — deferred; Personal Meeting Assistant uses
  file-based STT, so it isn't needed.
- Content Understanding multimodal **video/document** analysis — a separate, future ADR
  (the broader multi-service routing).
- Personal Meeting Assistant **TTS playback** — Personal Meeting Assistant advertises STT/voice-input only, no TTS provider slot;
  `gpt-4o-mini-tts` is provided for the playground/other OpenAI-audio clients until Personal Meeting Assistant TTS
  support is confirmed.

## Consequences

- Good, because it reuses ADR `0001`'s route, managed-identity auth, and Key model — zero new
  gateway architecture; any OpenAI-audio client (incl. Personal Meeting Assistant) works by setting base URL + Key.
- Good, because STT and TTS share one auth/route/scope, keeping the surface tiny.
- Bad, because the sync `/audio` API caps input at **25 MB** (~25–30 min); longer media needs
  a future batch/async path.
- Bad, because audio models are **regional** — the Foundry resource (or a dedicated audio
  deployment) must be in a region that lists them; this constrains region choice.
- Bad, because TTS models are **preview**, and content filtering is not applied to Whisper —
  note for governance.
- Follow-up: confirm whether Personal Meeting Assistant exposes a TTS setting; if not, TTS is exercised via the
  playground (ADR `0003`) and the test notebook.

## Implementation Plan

- **Affected paths**:
  - `personal-foundry-connection/infra/modules/foundry.bicep` — add model **deployments**
    for `gpt-4o-mini-transcribe` and `gpt-4o-mini-tts`; pin the resource/deployment to a
    region that offers them.
  - `personal-foundry-connection/src/sekisho/proxy.py` — ensure the passthrough handles
    **`multipart/form-data`** request bodies (STT upload) and **binary** responses
    (`audio/speech` returns audio bytes), streaming both without buffering the whole payload;
    preserve upstream `Content-Type`.
  - `personal-foundry-connection/src/sekisho/config.py` — optional `AUDIO_REGION` / model-name
    defaults (informational only; passthrough does not require them).
  - `personal-foundry-connection/docs/personal-meeting-assistant-setup.md` — the Personal Meeting Assistant Custom-STT cURL snippet
    (created when documentation is requested).
- **Dependencies**: none new — `httpx` already covers multipart upload and binary streaming.
- **Patterns to follow**: keep audio payloads **unmodeled** (passthrough); stream the binary
  TTS response straight to the caller; treat `/audio/*` as ordinary `/openai/*` traffic.
- **Patterns to avoid**: no audio transcoding/inspection; no full-buffering of large audio;
  no realtime/WebSocket path; do **not** deploy audio models in a region that lacks them;
  never expose a Foundry key to Personal Meeting Assistant.
- **Configuration**: Personal Meeting Assistant → Custom STT (cURL):
  ```bash
  curl -X POST "https://<sekisho-fqdn>/openai/v1/audio/transcriptions" \
    -H "Authorization: Bearer {{API_KEY}}" \
    -F "file=@{{AUDIO}}" \
    -F "model=gpt-4o-mini-transcribe" \
    -F "language={{LANGUAGE}}"
  ```

### Verification

- [ ] `POST /openai/v1/audio/transcriptions` through Sekisho with a multipart audio file +
      `model=gpt-4o-mini-transcribe` returns transcribed text.
- [ ] `POST /openai/v1/audio/speech` with `model=gpt-4o-mini-tts` returns playable audio
      bytes with the correct `Content-Type`, streamed (not buffered whole).
- [ ] Personal Meeting Assistant configured with the cURL template above transcribes captured audio via Sekisho
      using a Sekisho Key.
- [ ] No Foundry API key is present anywhere; audio calls use the managed-identity token
      (scope `https://ai.azure.com/.default`).
- [ ] Bicep deploys `gpt-4o-mini-transcribe` and `gpt-4o-mini-tts` in a region that lists them.
- [ ] An audio file over 25 MB is rejected with a clear error (documents the sync limit).

## Alternatives Considered

- **Azure Speech service** (`*.stt/tts.speech.microsoft.com`): real-time streaming and rich
  voices, but a separate host/scope and WebSocket complexity; rejected for v1 because Personal Meeting Assistant
  works with the OpenAI `/audio` shape and the gateway stays single-route.
- **Content Understanding for audio**: async multimodal *analysis* (transcripts, summaries),
  not low-latency STT, and not OpenAI-shaped; rejected for the STT/TTS use case (kept for a
  future video/document ADR).
- **`whisper` as the primary STT**: maximally compatible but older; kept as fallback, with
  `gpt-4o-mini-transcribe` preferred for quality.

## More Information

- Builds on `docs/adr/0001-adopt-managed-identity-reverse-proxy-gateway.md` (route, auth, Key).
- Foundry audio models & regions: Microsoft Learn "Foundry Models sold by Azure → Audio
  models" and "Audio capabilities in Azure OpenAI."
- Revisit if: real-time/low-latency speech-to-speech is needed (→ GPT-4o realtime WebSocket),
  inputs exceed 25 MB (→ batch transcription), or Personal Meeting Assistant adds a TTS provider slot.

### Model evaluation (2026-06-16) — newer models considered, deferred

A research pass evaluated newer 2026 models for a Personal Meeting Assistant-style live assistant. Recording why
they were **not** adopted here, so the choice isn't second-guessed later:

- **GPT-Realtime-Whisper** (streaming STT) and **`gpt-realtime` / `gpt-realtime-1.5`**
  (speech-to-speech) are real, but are consumed over **WebSocket/WebRTC**, not REST. They do
  not fit the `/openai/v1` HTTP passthrough — and decisively, **Personal Meeting Assistant's STT integration is
  file-based cURL** (`{{AUDIO}}`), so it cannot consume a streaming model at all. Moved to
  `docs/adr/0004-scope-realtime-voice-agent-capability.md`. (Regions: East US 2 / Sweden
  Central only.)
- **MAI-Voice-2** (TTS) is real but served via the **Azure Speech SSML API**
  (`cognitiveservices/v1` on a separate Speech resource/host/scope), not OpenAI
  `/audio/speech`. It offers better multilingual (PT-BR/ES/EN) expressivity, but requires the
  deferred multi-service `/speech` route — a separate future ADR, not a drop-in replacement
  for `gpt-4o-mini-tts`.
- **Unverified in public Microsoft Learn** (as of 2026-06-16): `MAI-Transcribe-1.5`,
  `GPT-Audio-1.5`, and `GPT-Realtime-2` by those exact names. The real equivalents are
  `gpt-4o-transcribe-diarize` (diarization) and `gpt-realtime-1.5` (2026-02-23). Source
  recommendations that cite internal-only links were not treated as authoritative.
- **Net**: `gpt-4o-mini-transcribe` / `gpt-4o-mini-tts` on the existing route remains the
  correct, lowest-effort choice for Personal Meeting Assistant; richer voice (MAI-Voice-2) and realtime
  (`0004`) are separate, higher-effort tracks.
