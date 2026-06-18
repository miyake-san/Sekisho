from pathlib import Path

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from sekisho.config import Settings
from sekisho.main import create_app


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk


def _settings(**overrides) -> Settings:
    values = {
        "FOUNDRY_BASE_URL": "https://foundry.test/openai/v1/",
        "SELF_BASE_URL": "http://self.test",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.anyio
async def test_playground_renders() -> None:
    app = create_app(_settings(PLAYGROUND_KEY="secret-playground-key"))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://sekisho.test") as client:
            response = await client.get("/playground")

    assert response.status_code == 200
    assert "Playground" in response.text
    assert "secret-playground-key" not in response.text


@pytest.mark.anyio
@respx.mock
async def test_playground_chat_streams_mocked_tokens() -> None:
    app = create_app(_settings(PLAYGROUND_KEY="secret-playground-key"))
    respx.post("http://self.test/openai/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            stream=ChunkStream([b"data: hello\n\n", b"data: world\n\n", b"data: [DONE]\n\n"]),
        )
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://sekisho.test") as client:
            async with client.stream("POST", "/playground/chat", data={"message": "Hi"}) as response:
                chunks = [chunk async for chunk in response.aiter_bytes()]

    assert response.status_code == 200
    assert b"".join(chunks) == b"data: hello\n\ndata: world\n\ndata: [DONE]\n\n"


@pytest.mark.anyio
async def test_playground_without_key_shows_disabled_notice() -> None:
    app = create_app(_settings())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://sekisho.test") as client:
            response = await client.get("/playground")

    assert response.status_code == 200
    assert "Set" in response.text
    assert "PLAYGROUND_KEY" in response.text
    assert "enabled: false" in response.text


@pytest.mark.anyio
async def test_secrets_do_not_appear_in_served_html_or_js() -> None:
    secret = "secret-playground-key"
    app = create_app(_settings(PLAYGROUND_KEY=secret, ADMIN_DEV_BYPASS=True, DEV_KEYS="gateway-secret-key"))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://sekisho.test") as client:
            playground = await client.get("/playground")
            admin = await client.get("/admin")
            app_js = await client.get("/static/app.js")

    assert secret not in playground.text
    assert secret not in admin.text
    assert "gateway-secret-key" not in admin.text
    assert secret not in app_js.text
    assert Path("src\\sekisho\\web\\static\\app.js").read_text(encoding="utf-8")
