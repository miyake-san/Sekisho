import pytest
from httpx import ASGITransport, AsyncClient

from sekisho.config import Settings
from sekisho.main import create_app


@pytest.mark.anyio
async def test_health_returns_ok() -> None:
    app = create_app(Settings(FOUNDRY_BASE_URL="https://foundry.test/openai/v1/"))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://sekisho.test") as client:
            response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
