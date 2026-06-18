---
status: proposed
date: 2026-06-16
decision-makers: Diogo Miyake (owner)
---

# Choose a lightweight server-rendered frontend (HTMX on FastAPI) for Sekisho

## Context and Problem Statement

Sekisho needs two small web surfaces before we build them ad hoc:

1. **Admin** — manage **Keys** (list, create, rotate, revoke), Entra-protected; this is the
   UI over the Key store from ADR `0001`.
2. **Playground** — exercise the gateway interactively: chat against `/openai/v1`, and test
   **STT/TTS** (record mic audio → transcription; type text → spoken audio) per ADR `0002`.

Constraints: the owner asked for the **most lightweight** stack; the backend is **FastAPI
(Python)** running as a single **Azure Container Apps** container; usage is owner/demo scale,
not a high-traffic public app. We want to avoid a second deployable, a Node build toolchain,
and SPA complexity unless they earn their keep.

The decision: which frontend stack, how it's served, and how admin is authenticated — made
now so coding starts against a settled choice.

## Decision

Adopt a **server-rendered frontend served by the same FastAPI app**:

- **HTMX + Jinja2** for pages and the admin CRUD (forms, partial swaps) — no SPA framework,
  no client-side router.
- **Alpine.js** for small local interactivity; **vanilla JS** (`MediaRecorder` for mic
  capture, `fetch` + streaming reads for chat SSE and audio playback) for the playground.
- **Pico.css** for styling — classless, no build step.
- All assets via **CDN/pinned static files** — **no Node build, no bundler**.
- **Admin authentication via Azure Container Apps built-in authentication (Easy Auth)** with
  Microsoft Entra — identity is injected by the platform; the app writes **no auth code** and
  reads the injected principal headers. The client **Key** is never used to authorize admin.

Everything ships in the **one FastAPI container** already defined for the gateway: a single
build, a single deploy, the smallest possible footprint.

**Non-goals:** a rich multi-page SPA; offline/PWA behavior; a design system; multi-user
account management beyond Entra sign-in.

## Consequences

- Good, because it adds **zero new deployables and no Node toolchain** — Python-only mental
  model, one container, one CI path.
- Good, because **Easy Auth** gives Entra-protected admin with no authentication code to
  write or maintain.
- Good, because HTMX is an excellent fit for the admin CRUD, and the playground's genuinely
  dynamic bits (audio, streaming) are a contained amount of vanilla JS.
- Bad, because if the playground later grows into a full app, vanilla JS will strain and a
  real component framework may be warranted (this ADR would be superseded).
- Bad, because audio capture/streaming is hand-written JS rather than provided by a UI library.
- Follow-up: enable Easy Auth in the ACA Bicep; gate `/admin/*` routes on the injected
  principal; keep the playground reachable but clearly separated from admin.

## Implementation Plan

- **Affected paths** (greenfield — create):
  - `personal-foundry-connection/src/sekisho/web/routes.py` — FastAPI routes for `/admin`
    (Key CRUD via HTMX partials) and `/playground` (chat + STT/TTS test).
  - `personal-foundry-connection/src/sekisho/web/templates/` — Jinja2 templates
    (`base.html`, `admin.html`, `playground.html`, plus HTMX partials).
  - `personal-foundry-connection/src/sekisho/web/static/` — `app.js` (Alpine init,
    `MediaRecorder`, streaming fetch), pinned `htmx.min.js`, `alpine.min.js`, `pico.min.css`.
  - `personal-foundry-connection/src/sekisho/main.py` — mount templates/static; mount the web
    router; the playground calls the gateway's own `/openai/v1/*` routes with a dev Key.
  - `personal-foundry-connection/infra/modules/aca.bicep` — enable **Container Apps
    authentication (Easy Auth)** with the Entra identity provider; require auth on `/admin/*`.
- **Dependencies**: `jinja2`, `python-multipart` (form posts/uploads). HTMX, Alpine, Pico via
  pinned static files — **no npm**.
- **Patterns to follow**: server-rendered pages + HTMX partial swaps for admin; read the Entra
  principal from Easy Auth headers (`X-MS-CLIENT-PRINCIPAL*`) for authorization; keep the
  playground's JS small and dependency-free.
- **Patterns to avoid**: do **not** introduce a Node/bundler build; do **not** add React/Vue/
  Svelte for v1; do **not** authorize admin actions with a client Key; do **not** embed any
  Key or secret in templates/JS served to the browser.
- **Configuration**: ACA auth (Easy Auth) Entra app registration; `ADMIN_GROUP`/allowed
  principal config if restricting beyond "authenticated."

### Verification

- [ ] The whole frontend is served by the single FastAPI container — no separate app, no
      Node build step in CI.
- [ ] Visiting `/admin/*` unauthenticated triggers Entra sign-in (Easy Auth); after sign-in
      the Key list renders.
- [ ] Creating, rotating, and revoking a Key from the admin UI updates the Key store and
      reflects via HTMX partial swap without a full page reload.
- [ ] The playground streams a chat completion from `/openai/v1` and renders tokens
      incrementally.
- [ ] The playground records mic audio, sends it to `/openai/v1/audio/transcriptions`, and
      shows the transcript; and plays back `/openai/v1/audio/speech` output.
- [ ] No Key or secret appears in any served HTML/JS payload.

## Alternatives Considered

- **Gradio**: fastest path to a Python chat+audio playground (built-in mic/audio, streaming),
  but heavy runtime, awkward for Key CRUD and Entra-gated admin, and not "lightweight";
  rejected as the primary stack (could be a throwaway demo, not the product UI).
- **Streamlit**: similar trade-offs to Gradio, worse for auth/CRUD and multipage; rejected.
- **SvelteKit / SolidJS**: small, modern SPA with great audio/streaming ergonomics, but adds
  a Node build and (typically) a second hosting path; rejected for v1 on "fewest moving
  parts," reconsider if the UI grows.
- **React**: most capable but the heaviest option; contradicts the lightweight constraint;
  rejected.
- **Server-side OIDC in-app (Authlib/MSAL)** instead of Easy Auth: more control but more auth
  code to own; rejected in favor of platform Easy Auth for v1.

## More Information

- Implements the management surface referenced in `0001` and the playground for `0002`.
- Revisit if: the playground evolves into a full interactive app (→ adopt a lightweight SPA
  and supersede this ADR), or admin needs fine-grained multi-user roles beyond Entra sign-in.
