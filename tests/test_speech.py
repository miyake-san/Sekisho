import httpx
import pytest
import respx


@pytest.mark.anyio
@respx.mock
async def test_speech_route_forwards_to_account_endpoint(speech_client) -> None:
    client, _ = speech_client
    route = respx.post(
        "https://foundry.test/speechtotext/transcriptions:transcribe?api-version=2025-10-15"
    ).mock(return_value=httpx.Response(200, json={"text": "hello"}))

    response = await client.post(
        "/speech/speechtotext/transcriptions:transcribe?api-version=2025-10-15",
        headers={"Authorization": "Bearer caller-key", "Content-Type": "application/json"},
        content=b'{"definition":{}}',
    )

    assert response.status_code == 200
    assert route.called
    # The Speech base URL is derived from FOUNDRY_BASE_URL by stripping openai/v1,
    # and the openai/v1 path rewrite is NOT applied to Speech requests.
    assert str(route.calls.last.request.url).startswith("https://foundry.test/speechtotext/")


@pytest.mark.anyio
@respx.mock
async def test_speech_route_uses_cognitiveservices_token(speech_client) -> None:
    client, _ = speech_client
    route = respx.post("https://foundry.test/speechtotext/transcriptions:transcribe").mock(
        return_value=httpx.Response(200, text="ok")
    )

    response = await client.post(
        "/speech/speechtotext/transcriptions:transcribe",
        headers={"Authorization": "Bearer caller-key"},
        content=b"{}",
    )

    assert response.status_code == 200
    # Speech requests must use the dedicated cognitiveservices-scoped token,
    # not the OpenAI (ai.azure.com) token.
    assert route.calls.last.request.headers["authorization"] == "Bearer speechtoken"


@pytest.mark.anyio
async def test_speech_route_requires_key(speech_client) -> None:
    client, _ = speech_client
    response = await client.post(
        "/speech/speechtotext/transcriptions:transcribe",
        content=b"{}",
    )
    assert response.status_code == 401
