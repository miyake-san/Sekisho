import logging

from fastapi import HTTPException, Request, status
from fastapi.security.utils import get_authorization_scheme_param

from sekisho.config import Settings
from sekisho.keys import KeyStore

logger = logging.getLogger("sekisho.auth")


async def validate_key_for_request(settings: Settings, key_store: KeyStore, authorization: str | None) -> None:
    if settings.anonymous_mode:
        return
    scheme, credential = get_authorization_scheme_param(authorization)
    if scheme.lower() != "bearer" or not credential:
        logger.warning("rejected request: missing or non-bearer authorization scheme")
        raise _unauthorized()
    if not await key_store.validate(credential):
        logger.warning("rejected request: bearer key failed validation")
        raise _unauthorized()


async def require_key(request: Request) -> None:
    await validate_key_for_request(
        request.app.state.settings,
        request.app.state.key_store,
        request.headers.get("authorization"),
    )


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid bearer Key",
        headers={"WWW-Authenticate": "Bearer"},
    )
