import gzip

import httpx
import pytest
import respx


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk


@pytest.mark.anyio
@respx.mock
async def test_unknown_openai_field_forwarded_unchanged(proxy_client) -> None:
    client, _ = proxy_client
    body = b'{"model":"deployment","messages":[],"future_unknown_field":{"x":1}}'
    route = respx.post("https://foundry.test/openai/v1/chat/completions?stream=false").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    response = await client.post(
        "/openai/v1/chat/completions?stream=false",
        headers={"Authorization": "Bearer caller-key", "Content-Type": "application/json"},
        content=body,
    )

    assert response.status_code == 200
    assert route.called
    assert route.calls.last.request.content == body


@pytest.mark.anyio
@respx.mock
async def test_authorization_replaced_with_managed_identity_token(proxy_client) -> None:
    client, _ = proxy_client
    route = respx.post("https://foundry.test/openai/v1/responses").mock(return_value=httpx.Response(200, text="ok"))

    response = await client.post("/openai/v1/responses", headers={"Authorization": "Bearer caller-key"}, content=b"{}")

    assert response.status_code == 200
    assert route.calls.last.request.headers["authorization"] == "Bearer faketoken"


@pytest.mark.anyio
@respx.mock
async def test_sse_stream_passes_through(proxy_client) -> None:
    client, _ = proxy_client
    chunks = [b"data: one\n\n", b"data: two\n\n"]
    respx.post("https://foundry.test/openai/v1/chat/completions").mock(
        return_value=httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=ChunkStream(chunks))
    )

    async with client.stream(
        "POST",
        "/openai/v1/chat/completions",
        headers={"Authorization": "Bearer caller-key"},
        content=b'{"stream":true}',
    ) as response:
        received = [chunk async for chunk in response.aiter_bytes()]

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert b"".join(received) == b"".join(chunks)


@pytest.mark.anyio
@respx.mock
async def test_multipart_content_type_boundary_preserved(proxy_client) -> None:
    client, _ = proxy_client
    route = respx.post("https://foundry.test/openai/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "hi"})
    )
    content_type = "multipart/form-data; boundary=sekisho-boundary"
    body = (
        b"--sekisho-boundary\r\n"
        b'Content-Disposition: form-data; name="model"\r\n\r\n'
        b"gpt-4o-mini-transcribe\r\n"
        b"--sekisho-boundary--\r\n"
    )

    response = await client.post(
        "/openai/v1/audio/transcriptions",
        headers={"Authorization": "Bearer caller-key", "Content-Type": content_type},
        content=body,
    )

    assert response.status_code == 200
    assert route.calls.last.request.headers["content-type"] == content_type
    assert route.calls.last.request.content == body


@pytest.mark.anyio
@respx.mock
async def test_binary_audio_response_preserved(proxy_client) -> None:
    client, _ = proxy_client
    audio = b"\x00\x01mp3-bytes"
    respx.post("https://foundry.test/openai/v1/audio/speech").mock(
        return_value=httpx.Response(200, headers={"Content-Type": "audio/mpeg"}, content=audio)
    )

    response = await client.post("/openai/v1/audio/speech", headers={"Authorization": "Bearer caller-key"}, content=b"{}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == audio


@pytest.mark.anyio
@respx.mock
async def test_upstream_401_force_refreshes_once_and_retries(proxy_client) -> None:
    client, token_provider = proxy_client
    route = respx.post("https://foundry.test/openai/v1/responses").mock(
        side_effect=[httpx.Response(401, text="expired"), httpx.Response(200, text="ok")]
    )

    response = await client.post("/openai/v1/responses", headers={"Authorization": "Bearer caller-key"}, content=b"{}")

    assert response.status_code == 200
    assert response.text == "ok"
    assert token_provider.force_refresh_count == 1
    assert route.call_count == 2
    assert route.calls[0].request.headers["authorization"] == "Bearer faketoken"
    assert route.calls[1].request.headers["authorization"] == "Bearer refreshedtoken"


@pytest.mark.anyio
@respx.mock
async def test_gzip_response_is_decoded_and_encoding_header_dropped(proxy_client) -> None:
    client, _ = proxy_client
    payload = b'{"ok": true}'
    respx.post("https://foundry.test/openai/v1/responses").mock(
        return_value=httpx.Response(
            200,
            headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
            content=gzip.compress(payload),
        )
    )

    response = await client.post(
        "/openai/v1/responses",
        headers={"Authorization": "Bearer caller-key"},
        content=b"{}",
    )

    assert response.status_code == 200
    # The proxy must hand back the decoded body and must not claim it is still
    # gzip-encoded, otherwise the client cannot read it.
    assert response.content == payload
    assert "content-encoding" not in response.headers
