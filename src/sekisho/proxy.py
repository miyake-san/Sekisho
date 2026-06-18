from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from typing import Protocol
from urllib.parse import urljoin

import httpx
from fastapi import Request
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

logger = logging.getLogger("sekisho.proxy")


class _TokenProvider(Protocol):
    async def get_token(self) -> str: ...

    async def force_refresh(self) -> str: ...

HOP_BY_HOP_HEADERS = {
    "host",
    "content-length",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
RESPONSE_DROP_HEADERS = HOP_BY_HOP_HEADERS | {"content-encoding"}


def _upstream_url(base_url: str, path: str, query: bytes, *, rewrite_openai_v1: bool = True) -> str:
    clean_base = base_url.rstrip("/") + "/"
    clean_path = path.lstrip("/")
    if rewrite_openai_v1 and clean_base.rstrip("/").endswith("/openai/v1") and clean_path.startswith("v1/"):
        clean_path = clean_path[3:]
    url = urljoin(clean_base, clean_path)
    if query:
        return f"{url}?{query.decode('latin-1')}"
    return url


def _forward_headers(request: Request, token: str) -> dict[str, str]:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "authorization"
    }
    headers["Authorization"] = f"Bearer {token}"
    return headers


def _response_headers(upstream: httpx.Response) -> dict[str, str]:
    return {key: value for key, value in upstream.headers.items() if key.lower() not in RESPONSE_DROP_HEADERS}


async def proxy_request(request: Request) -> StreamingResponse:
    """Proxy an OpenAI-compatible request to the Foundry OpenAI v1 endpoint."""
    settings = request.app.state.settings
    return await _proxy(
        request,
        base_url=settings.foundry_base_url,
        token_provider=request.app.state.token_provider,
        rewrite_openai_v1=True,
    )


async def speech_proxy_request(request: Request) -> StreamingResponse:
    """Proxy an Azure Speech (cognitiveservices) request to the Foundry account endpoint.

    Used for the Speech REST surface (e.g. fast/batch transcription with
    ``mai-transcribe-1``) so third-party tools can reach it through Sekisho.
    The Speech data plane uses a different Entra scope than the OpenAI
    endpoint, so a dedicated token provider is used and no ``openai/v1`` path
    rewrite is applied.
    """
    settings = request.app.state.settings
    return await _proxy(
        request,
        base_url=settings.speech_base_url,
        token_provider=request.app.state.speech_token_provider,
        rewrite_openai_v1=False,
    )


async def _proxy(
    request: Request,
    *,
    base_url: str,
    token_provider: _TokenProvider,
    rewrite_openai_v1: bool,
) -> StreamingResponse:
    path = request.path_params.get("path", "")
    client: httpx.AsyncClient = request.app.state.http_client
    # The request body is buffered in memory so it can be replayed on a 401
    # token-refresh retry. This is fine for chat/JSON payloads but means large
    # audio uploads are held fully in memory; revisit with a size guard if
    # streaming large multipart uploads becomes a hot path.
    body_chunks: list[bytes] = []

    async def first_body() -> AsyncIterator[bytes]:
        async for chunk in request.stream():
            body_chunks.append(chunk)
            yield chunk

    async def replay_body() -> AsyncIterator[bytes]:
        for chunk in body_chunks:
            yield chunk

    upstream = await _send_once(
        request, client, base_url, path, await token_provider.get_token(), first_body, rewrite_openai_v1
    )
    if upstream.status_code == 401:
        logger.info("upstream returned 401; forcing token refresh and retrying once")
        await upstream.aclose()
        token = await token_provider.force_refresh()
        upstream = await _send_once(request, client, base_url, path, token, replay_body, rewrite_openai_v1)

    # aiter_bytes() lets httpx transparently decode any content-encoding (e.g.
    # gzip) applied by the upstream. We therefore strip content-encoding from
    # the forwarded response headers (see RESPONSE_DROP_HEADERS) so clients are
    # never told the already-decoded body is still compressed.
    return StreamingResponse(
        upstream.aiter_bytes(),
        status_code=upstream.status_code,
        headers=_response_headers(upstream),
        background=BackgroundTask(upstream.aclose),
    )


async def _send_once(
    request: Request,
    client: httpx.AsyncClient,
    base_url: str,
    path: str,
    token: str,
    body_factory: Callable[[], AsyncIterator[bytes]],
    rewrite_openai_v1: bool = True,
) -> httpx.Response:
    upstream_request = client.build_request(
        method=request.method,
        url=_upstream_url(base_url, path, request.url.query.encode("latin-1"), rewrite_openai_v1=rewrite_openai_v1),
        headers=_forward_headers(request, token),
        content=body_factory(),
    )
    return await client.send(upstream_request, stream=True)
