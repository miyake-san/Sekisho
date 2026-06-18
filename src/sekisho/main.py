import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from azure.identity import DefaultAzureCredential
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sekisho.auth import require_key
from sekisho.config import Settings, get_settings
from sekisho.foundry_token import FoundryTokenProvider
from sekisho.keys import build_key_store
from sekisho.proxy import proxy_request, speech_proxy_request
from sekisho.web.routes import router as web_router


def include_future_routers(app: FastAPI) -> None:
    web_dir = Path(__file__).parent / "web"
    app.state.templates = Jinja2Templates(directory=web_dir / "templates")
    app.mount("/static", StaticFiles(directory=web_dir / "static"), name="static")
    app.include_router(web_router)


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved_settings = settings or get_settings()
        credential = DefaultAzureCredential()
        token_provider = FoundryTokenProvider(
            scope=resolved_settings.foundry_token_scope,
            credential=credential,
        )
        speech_token_provider = FoundryTokenProvider(
            scope=resolved_settings.speech_token_scope,
            credential=credential,
        )
        key_store = build_key_store(resolved_settings, credential)
        http_client = httpx.AsyncClient(timeout=None)

        app.state.settings = resolved_settings
        app.state.credential = credential
        app.state.token_provider = token_provider
        app.state.speech_token_provider = speech_token_provider
        app.state.key_store = key_store
        app.state.http_client = http_client
        try:
            yield
        finally:
            await http_client.aclose()
            close_key_store = getattr(key_store, "close", None)
            if close_key_store is not None:
                await close_key_store()
            await token_provider.close()
            await speech_token_provider.close()

    app = FastAPI(title="Sekisho", lifespan=lifespan)

    if settings is not None:
        cors_origins = settings.cors_origin_list
    else:
        raw_origins = os.getenv("CORS_ALLOW_ORIGINS", "*")
        cors_origins = ["*"] if raw_origins.strip() == "*" else [o.strip() for o in raw_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/playground")

    @app.get("/health", include_in_schema=False)
    @app.get("/healthz", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.api_route(
        "/openai/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        dependencies=[Depends(require_key)],
    )
    async def openai_proxy(path: str, request: Request):
        return await proxy_request(request)

    @app.api_route(
        "/speech/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        dependencies=[Depends(require_key)],
    )
    async def speech_proxy(path: str, request: Request):
        return await speech_proxy_request(request)

    include_future_routers(app)
    return app


app = create_app()
