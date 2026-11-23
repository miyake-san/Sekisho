from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Annotated
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

from sekisho.config import Settings
from sekisho.keys import CreatedKey, KeyStore

router = APIRouter()

_ADMIN_COOKIE = "sekisho_admin"
_ADMIN_MAX_AGE = 60 * 60 * 12  # 12 hours


def _admin_secret(settings: Settings) -> str:
    return settings.admin_session_secret or settings.admin_password or ""


def _sign_admin_token(settings: Settings) -> str:
    issued = str(int(time.time()))
    sig = hmac.new(_admin_secret(settings).encode(), issued.encode(), hashlib.sha256).hexdigest()
    return f"{issued}.{sig}"


def _verify_admin_token(settings: Settings, token: str | None) -> bool:
    if not token or "." not in token:
        return False
    issued, _, sig = token.partition(".")
    expected = hmac.new(_admin_secret(settings).encode(), issued.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        issued_at = int(issued)
    except ValueError:
        return False
    return (time.time() - issued_at) <= _ADMIN_MAX_AGE


def _templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _key_store(request: Request) -> KeyStore:
    return request.app.state.key_store


def _principal_from_encoded_header(value: str | None) -> str | None:
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        principal = json.loads(base64.b64decode(padded))
    except (ValueError, json.JSONDecodeError):
        return None
    for key in ("userDetails", "userId", "name", "auth_typ"):
        candidate = principal.get(key)
        if candidate:
            return str(candidate)
    return None


async def require_admin(request: Request) -> str:
    settings = _settings(request)
    if settings.admin_dev_bypass:
        return "dev"

    # App-level password login (no Entra). Only the signed cookie is trusted,
    # so this stays safe even when Easy Auth is disabled in front of the app.
    if settings.admin_password:
        if _verify_admin_token(settings, request.cookies.get(_ADMIN_COOKIE)):
            return "admin"
        login_url = "/admin/login"
        headers = (
            {"HX-Redirect": login_url}
            if request.headers.get("HX-Request") == "true"
            else {"Location": login_url}
        )
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers=headers)

    # SECURITY: X-MS-CLIENT-PRINCIPAL-NAME / X-MS-CLIENT-PRINCIPAL are trusted
    # only because Azure App Service EasyAuth injects them and strips any
    # client-supplied copies at the front door. If this app is ever exposed
    # without EasyAuth (or an equivalent gateway) in front, these headers can be
    # spoofed and admin auth is bypassed. Keep EasyAuth in front in production.
    principal_name = request.headers.get("X-MS-CLIENT-PRINCIPAL-NAME") or _principal_from_encoded_header(
        request.headers.get("X-MS-CLIENT-PRINCIPAL")
    )
    if principal_name:
        return principal_name

    requested_path = request.url.path
    if request.url.query:
        requested_path = f"{requested_path}?{request.url.query}"
    login_url = f"/.auth/login/aad?post_login_redirect_uri={quote(requested_path, safe='')}"
    headers = {"HX-Redirect": login_url} if request.headers.get("HX-Request") == "true" else {"Location": login_url}
    raise HTTPException(status_code=status.HTTP_302_FOUND, headers=headers)


async def _render_key_list(request: Request, keys: list[str], revoked_name: str | None = None):
    return _templates(request).TemplateResponse(request, "partials/_key_list.html", {"keys": keys, "revoked_name": revoked_name})


async def _created_key_response(request: Request, created_key: CreatedKey):
    keys = await _key_store(request).list_keys()
    return _templates(request).TemplateResponse(
        request,
        "partials/_created_key.html",
        {"created_key": created_key, "keys": keys, "error": None},
    )


@router.get("/admin/login")
async def admin_login_page(request: Request):
    settings = _settings(request)
    if not settings.admin_password:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if _verify_admin_token(settings, request.cookies.get(_ADMIN_COOKIE)):
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    return _templates(request).TemplateResponse(request, "login.html", {"error": None})


@router.post("/admin/login")
async def admin_login(request: Request, password: Annotated[str, Form()]):
    settings = _settings(request)
    if not settings.admin_password:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not hmac.compare_digest(password, settings.admin_password):
        return _templates(request).TemplateResponse(
            request,
            "login.html",
            {"error": "Senha invalida."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        _ADMIN_COOKIE,
        _sign_admin_token(settings),
        max_age=_ADMIN_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response


@router.post("/admin/logout")
async def admin_logout(request: Request):
    response = RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(_ADMIN_COOKIE)
    return response


@router.get("/admin")
async def admin_page(request: Request, principal_name: Annotated[str, Depends(require_admin)]):
    keys = await _key_store(request).list_keys()
    return _templates(request).TemplateResponse(
        request,
        "admin.html",
        {"keys": keys, "principal_name": principal_name, "error": None},
    )


@router.post("/admin/keys")
async def create_key(
    request: Request,
    principal_name: Annotated[str, Depends(require_admin)],
    name: Annotated[str, Form()],
):
    try:
        created_key = await _key_store(request).create(name.strip())
    except ValueError as exc:
        keys = await _key_store(request).list_keys()
        return _templates(request).TemplateResponse(
            request,
            "partials/_created_key.html",
            {"created_key": None, "keys": keys, "error": str(exc)},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return await _created_key_response(request, created_key)


@router.post("/admin/keys/{name}/rotate")
async def rotate_key(
    request: Request,
    principal_name: Annotated[str, Depends(require_admin)],
    name: str,
    grace_seconds: Annotated[int, Form()] = 3600,
):
    try:
        created_key = await _key_store(request).rotate(name, grace_seconds)
    except (KeyError, ValueError) as exc:
        keys = await _key_store(request).list_keys()
        return _templates(request).TemplateResponse(
            request,
            "partials/_created_key.html",
            {"created_key": None, "keys": keys, "error": f"Unable to rotate key: {exc}"},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return await _created_key_response(request, created_key)


@router.post("/admin/keys/{name}/revoke")
async def revoke_key(request: Request, principal_name: Annotated[str, Depends(require_admin)], name: str):
    try:
        await _key_store(request).revoke(name)
    except KeyError:
        pass
    keys = await _key_store(request).list_keys()
    return await _render_key_list(request, keys, revoked_name=name)


@router.get("/playground")
async def playground_page(request: Request):
    settings = _settings(request)
    return _templates(request).TemplateResponse(
        request,
        "playground.html",
        {"playground_enabled": bool(settings.playground_key), "chat_model": settings.chat_model},
    )


async def _read_message(request: Request) -> str:
    content_type = request.headers.get("content-type", "").split(";", 1)[0]
    if content_type == "application/json":
        body = await request.json()
        return str(body.get("message", ""))
    form = await request.form()
    return str(form.get("message", ""))


def _playground_headers(settings: Settings) -> dict[str, str]:
    if not settings.playground_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PLAYGROUND_KEY is not configured")
    return {"Authorization": f"Bearer {settings.playground_key}"}


async def _streaming_response_from_context(response_ctx, default_media_type: str) -> StreamingResponse:
    upstream = await response_ctx.__aenter__()
    try:
        upstream.raise_for_status()
    except httpx.HTTPStatusError:
        await response_ctx.__aexit__(None, None, None)
        raise
    return StreamingResponse(
        upstream.aiter_bytes(),
        status_code=upstream.status_code,
        headers={"Content-Type": upstream.headers.get("content-type", default_media_type)},
        background=BackgroundTask(response_ctx.__aexit__, None, None, None),
    )


@router.post("/playground/chat")
async def playground_chat(request: Request):
    settings = _settings(request)
    user_message = (await _read_message(request)).strip()
    if not user_message:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Message is required")

    client: httpx.AsyncClient = request.app.state.http_client
    upstream = client.stream(
        "POST",
        f"{settings.self_base_url.rstrip('/')}/openai/v1/chat/completions",
        headers=_playground_headers(settings),
        json={
            "model": settings.chat_model,
            "messages": [{"role": "user", "content": user_message}],
            "stream": True,
        },
    )
    return await _streaming_response_from_context(upstream, "text/event-stream")


@router.post("/playground/transcribe")
async def playground_transcribe(
    request: Request,
    file: Annotated[UploadFile, File()],
    language: Annotated[str | None, Form()] = None,
):
    settings = _settings(request)
    data = {"model": settings.stt_model}
    if language:
        data["language"] = language
    files = {"file": (file.filename or "audio.webm", await file.read(), file.content_type or "application/octet-stream")}
    client: httpx.AsyncClient = request.app.state.http_client
    upstream = await client.post(
        f"{settings.self_base_url.rstrip('/')}/openai/v1/audio/transcriptions",
        headers=_playground_headers(settings),
        data=data,
        files=files,
    )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers={"Content-Type": upstream.headers.get("content-type", "application/json")},
    )


@router.post("/playground/speak")
async def playground_speak(request: Request, text: Annotated[str, Form()]):
    settings = _settings(request)
    client: httpx.AsyncClient = request.app.state.http_client
    upstream = client.stream(
        "POST",
        f"{settings.self_base_url.rstrip('/')}/openai/v1/audio/speech",
        headers=_playground_headers(settings),
        json={"model": settings.tts_model, "input": text, "voice": "alloy"},
    )
    return await _streaming_response_from_context(upstream, "audio/mpeg")
