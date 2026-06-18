import pytest
from fastapi import HTTPException

from sekisho.auth import validate_key_for_request
from sekisho.config import Settings
from sekisho.keys import InMemoryKeyStore


@pytest.mark.anyio
async def test_anonymous_mode_allows_without_key() -> None:
    settings = Settings(FOUNDRY_BASE_URL="https://foundry.test/openai/v1/", ANONYMOUS_MODE=True)
    await validate_key_for_request(settings, InMemoryKeyStore(), None)


@pytest.mark.anyio
async def test_missing_or_invalid_key_returns_401() -> None:
    settings = Settings(FOUNDRY_BASE_URL="https://foundry.test/openai/v1/")
    store = InMemoryKeyStore(["valid"])

    with pytest.raises(HTTPException) as missing:
        await validate_key_for_request(settings, store, None)
    assert missing.value.status_code == 401
    assert missing.value.headers == {"WWW-Authenticate": "Bearer"}

    with pytest.raises(HTTPException) as invalid:
        await validate_key_for_request(settings, store, "Bearer wrong")
    assert invalid.value.status_code == 401


@pytest.mark.anyio
async def test_valid_key_passes() -> None:
    settings = Settings(FOUNDRY_BASE_URL="https://foundry.test/openai/v1/")
    await validate_key_for_request(settings, InMemoryKeyStore(["valid"]), "Bearer valid")
