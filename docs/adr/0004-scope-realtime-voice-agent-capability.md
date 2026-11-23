---
status: proposed
date: 2026-06-16
decision-makers: Diogo Miyake (owner)
---

# Scope a realtime voice-agent capability as a separate track (not the passthrough gateway)

## Context and Problem Statement

A research pass (recorded in ADR `0002`) raised newer Foundry models aimed at a "live
conversation" assistant — **GPT-Realtime-Whisper** (streaming transcription) and the
**`gpt-realtime`** family (speech-to-speech). These are attractive for an always-listening,
interruptible voice agent, but they consume fundamentally differently from everything Sekisho
does today:

- Sekisho (ADR `0001`/`0002`) is an **HTTP request/response reverse proxy**. Audio in `0002`
  is *file-based* REST (`/audio/transcriptions`, `/audio/speech`).
- The realtime models are consumed over **WebSocket, WebRTC, or SIP** — long-lived,
  bidirectional, streaming media sessions, not request/response.
- The first concrete consumer, some **Personal Meeting Assistant**, uses a *file-based cURL* STT slot and therefore
  **cannot use a streaming realtime model at all.**

So "add realtime" is not a feature on the existing gateway — it's a different architecture
with different auth and a different client contract. This ADR records that boundary and the
intended approach **if/when** a realtime voice agent is actually pursued, so the decision and
its constraints aren't re-litigated from scratch.

Validated against Microsoft Learn (2026-06-16): realtime models, protocols, and regions below.

## Decision

- **Realtime voice is a separate capability, explicitly out of scope for Sekisho v1.** It is
  **not** routed through the `/openai/v1` HTTP passthrough. The gateway does not proxy
  real-time media.
- **When pursued, prefer the "session-minting" pattern, not media proxying:** a thin Sekisho
  endpoint validates a caller **Key** and mints a **short-lived ephemeral credential/session**
  for Foundry's Realtime API; the client then connects **directly to Foundry over WebRTC**
  (browser/app) or the server uses **WebSocket** (server-to-server). The managed identity
  stays server-side and is never shipped to a client; media never transits the gateway.
- **Models** (deploy via Bicep/CLI like any base model): `gpt-realtime` (or `gpt-realtime-1.5`)
  for speech-to-speech, **GPT-Realtime-Whisper** for parallel streaming transcription.
- **Hard region constraint**: realtime models are available only in **East US 2** and
  **Sweden Central** (global standard). If realtime is pursued, the realtime resource pins to
  one of these — independent of the region chosen for the `0002` audio models.

**Non-goals (now):** any realtime work in v1; Personal Meeting Assistant integration (it can't consume realtime);
SIP/telephony; WebRTC media relay through the gateway.

## Consequences

- Good, because it draws a clean architectural line: the passthrough gateway stays simple, and
  realtime — with its different protocol, auth, and lifecycle — doesn't contaminate it.
- Good, because session-minting keeps the managed identity server-side and avoids proxying
  latency-sensitive media (WebRTC is ~50–100 ms; relaying through ACA would add latency and
  cost).
- Bad, because a future realtime agent needs a distinct service/codebase (WS/WebRTC session
  handling, ephemeral-credential issuance) — real new work, not a config toggle.
- Bad, because the region pin (EUS2 / Sweden Central) may differ from the rest of the stack,
  splitting deployment topology.
- Follow-up (only if pursued): a session-mint endpoint, an ephemeral-credential flow, a
  realtime model deployment, and a client (WebRTC) reference.

## Implementation Plan

> Deferred — execute only if/when a realtime voice agent is greenlit.

- **Affected paths** (future): `personal-foundry-connection/src/sekisho/realtime/session.py`
  (Key-validated ephemeral-session mint endpoint); `infra/modules/foundry-realtime.bicep`
  (deploy `gpt-realtime` + GPT-Realtime-Whisper in EUS2 / Sweden Central); a separate
  `clients/realtime-webrtc/` reference.
- **Dependencies** (future): `websockets` + `azure-identity` (server-side WS path); WebRTC on
  the client side. None added to v1.
- **Patterns to follow**: mint short-lived sessions, connect client↔Foundry directly; keep MI
  server-side; treat realtime as its own bounded service.
- **Patterns to avoid**: do **not** proxy WebRTC/WebSocket media through the gateway; do
  **not** expose the managed-identity token to clients; do **not** fold realtime routes into
  the `/openai/v1` passthrough.

### Verification

- [ ] Sekisho v1 contains **no** realtime/WebSocket route (confirms the boundary holds).
- [ ] If/when built: a client obtains a short-lived session by presenting a Key, then streams
      audio directly to Foundry over WebRTC without the gateway relaying media.
- [ ] The managed-identity token never appears client-side; clients only ever hold a Key or an
      ephemeral session credential.
- [ ] Realtime model deployment targets East US 2 or Sweden Central.

## Alternatives Considered

- **Proxy WebSocket/WebRTC media through Sekisho**: keeps one entry point, but adds latency,
  cost, and significant complexity to a service designed for stateless HTTP passthrough;
  rejected — media should go client↔Foundry directly.
- **Bend Personal Meeting Assistant into realtime**: not possible — Personal Meeting Assistant's STT is file-based cURL; rejected.
- **SIP/telephony ingress**: real (Realtime API supports SIP) but only relevant for phone
  systems; out of scope.
- **Do it all in v1**: rejected — disproportionate to the v1 goal (file-based STT/TTS for
  Personal Meeting Assistant) and unused by the only current consumer.

## More Information

- Spun out of ADR `0002` (audio STT/TTS) "Model evaluation."
- Microsoft Learn: "Use the GPT Realtime API" (WebSockets / WebRTC / SIP), "GPT Realtime
  Whisper overview," and realtime model region availability (East US 2 / Sweden Central).
- Revisit when: there's a concrete need for a live, interruptible voice agent beyond Personal Meeting Assistant
  (e.g., a Teams meeting copilot), at which point this ADR becomes the starting point.
