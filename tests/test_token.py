import pytest
from azure.core.credentials import AccessToken

from sekisho.foundry_token import FoundryTokenProvider


class FakeCredential:
    def __init__(self) -> None:
        self.calls = 0
        self.expires_on = 2_000_000_000

    def get_token(self, scope: str) -> AccessToken:
        self.calls += 1
        return AccessToken(f"token-{self.calls}", self.expires_on)


@pytest.mark.anyio
async def test_token_cached_on_first_call() -> None:
    credential = FakeCredential()
    provider = FoundryTokenProvider("scope", credential=credential)

    assert await provider.get_token() == "token-1"
    assert await provider.get_token() == "token-1"
    assert credential.calls == 1


@pytest.mark.anyio
async def test_token_refreshes_when_near_expiry() -> None:
    credential = FakeCredential()
    credential.expires_on = 0
    provider = FoundryTokenProvider("scope", credential=credential)

    assert await provider.get_token() == "token-1"
    assert await provider.get_token() == "token-2"
    assert credential.calls == 2


@pytest.mark.anyio
async def test_force_refresh_gets_new_token() -> None:
    credential = FakeCredential()
    provider = FoundryTokenProvider("scope", credential=credential)

    assert await provider.get_token() == "token-1"
    assert await provider.force_refresh() == "token-2"
    assert await provider.get_token() == "token-2"
    assert credential.calls == 2
