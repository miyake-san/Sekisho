import pytest
from httpx import ASGITransport, AsyncClient

from sekisho.config import Settings
from sekisho.keys import InMemoryKeyStore
from sekisho.main import create_app


def _settings(**overrides) -> Settings:
    values = {"FOUNDRY_BASE_URL": "https://foundry.test/openai/v1/"}
    values.update(overrides)
    return Settings(**values)


@pytest.mark.anyio
async def test_admin_without_principal_redirects_to_easy_auth() -> None:
    app = create_app(_settings())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://sekisho.test") as client:
            response = await client.get("/admin", follow_redirects=False)
            htmx_response = await client.get("/admin", headers={"HX-Request": "true"}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("/.auth/login/aad")
    assert htmx_response.status_code == 302
    assert htmx_response.headers["hx-redirect"].startswith("/.auth/login/aad")


@pytest.mark.anyio
async def test_admin_with_principal_renders_key_list() -> None:
    app = create_app(_settings(DEV_KEYS="caller-key"))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://sekisho.test") as client:
            response = await client.get("/admin", headers={"X-MS-CLIENT-PRINCIPAL-NAME": "owner@example.test"})

    assert response.status_code == 200
    assert "owner@example.test" in response.text
    assert "dev-1" in response.text


@pytest.mark.anyio
async def test_admin_dev_bypass_renders_key_list() -> None:
    app = create_app(_settings(ADMIN_DEV_BYPASS=True, DEV_KEYS="caller-key"))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://sekisho.test") as client:
            response = await client.get("/admin")

    assert response.status_code == 200
    assert "Signed in as" in response.text
    assert "dev-1" in response.text


@pytest.mark.anyio
async def test_admin_create_shows_new_value_once_and_lists_key() -> None:
    app = create_app(_settings(ADMIN_DEV_BYPASS=True))
    async with app.router.lifespan_context(app):
        store = InMemoryKeyStore()
        app.state.key_store = store
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://sekisho.test") as client:
            response = await client.post("/admin/keys", data={"name": "demo"})
            keys = await store.list_keys()

    assert response.status_code == 200
    assert "Store this Key now" in response.text
    assert "This secret value is shown exactly once" in response.text
    assert "demo" in response.text
    assert keys == ["demo"]


@pytest.mark.anyio
async def test_admin_rotate_and_revoke_work() -> None:
    app = create_app(_settings(ADMIN_DEV_BYPASS=True))
    async with app.router.lifespan_context(app):
        store = InMemoryKeyStore()
        await store.create("demo")
        app.state.key_store = store
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://sekisho.test") as client:
            rotate = await client.post("/admin/keys/demo/rotate", data={"grace_seconds": "60"})
            revoke = await client.post("/admin/keys/demo/revoke")

    assert rotate.status_code == 200
    assert "Store this Key now" in rotate.text
    assert revoke.status_code == 200
    assert "key-list" in revoke.text


@pytest.mark.anyio
async def test_gateway_key_does_not_authorize_admin() -> None:
    app = create_app(_settings(DEV_KEYS="caller-key"))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://sekisho.test") as client:
            response = await client.get("/admin", headers={"Authorization": "Bearer caller-key"}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("/.auth/login/aad")
