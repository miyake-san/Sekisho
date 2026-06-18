import pytest
from httpx import ASGITransport, AsyncClient

from sekisho.config import Settings
from sekisho.keys import InMemoryKeyStore
from sekisho.main import create_app


class FakeTokenProvider:
    def __init__(self, token: str = "faketoken") -> None:
        self.token = token
        self.force_refresh_count = 0

    async def get_token(self) -> str:
        return self.token

    async def force_refresh(self) -> str:
        self.force_refresh_count += 1
        self.token = "refreshedtoken"
        return self.token


@pytest.fixture
def settings() -> Settings:
    return Settings(FOUNDRY_BASE_URL="https://foundry.test/openai/v1/", DEV_KEYS="caller-key")


@pytest.fixture
async def proxy_client(settings: Settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        fake_token_provider = FakeTokenProvider()
        app.state.token_provider = fake_token_provider
        app.state.speech_token_provider = FakeTokenProvider("speechtoken")
        app.state.key_store = InMemoryKeyStore(["caller-key"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://sekisho.test") as client:
            yield client, fake_token_provider


@pytest.fixture
async def speech_client(settings: Settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        fake_token_provider = FakeTokenProvider()
        speech_token_provider = FakeTokenProvider("speechtoken")
        app.state.token_provider = fake_token_provider
        app.state.speech_token_provider = speech_token_provider
        app.state.key_store = InMemoryKeyStore(["caller-key"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://sekisho.test") as client:
            yield client, speech_token_provider
