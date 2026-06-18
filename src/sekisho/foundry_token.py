import asyncio
import logging
import time

import anyio
from azure.core.credentials import AccessToken, TokenCredential
from azure.identity import DefaultAzureCredential

logger = logging.getLogger("sekisho.token")


class FoundryTokenProvider:
    def __init__(
        self,
        scope: str = "https://ai.azure.com/.default",
        credential: TokenCredential | None = None,
        refresh_margin_seconds: int = 300,
    ) -> None:
        self._scope = scope
        self._credential = credential or DefaultAzureCredential()
        self._refresh_margin_seconds = refresh_margin_seconds
        self._token: AccessToken | None = None
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        async with self._lock:
            if self._token is None or self._is_expiring(self._token):
                self._token = await self._fetch_token()
            return self._token.token

    async def force_refresh(self) -> str:
        async with self._lock:
            logger.info("force-refreshing Foundry access token")
            self._token = await self._fetch_token()
            return self._token.token

    def _is_expiring(self, token: AccessToken) -> bool:
        return token.expires_on <= time.time() + self._refresh_margin_seconds

    async def _fetch_token(self) -> AccessToken:
        token = await anyio.to_thread.run_sync(self._credential.get_token, self._scope)
        logger.debug("acquired Foundry access token (expires_on=%s)", token.expires_on)
        return token

    async def close(self) -> None:
        close = getattr(self._credential, "close", None)
        if close is None:
            return
        result = close()
        if hasattr(result, "__await__"):
            await result

    @property
    def credential(self) -> TokenCredential:
        return self._credential
