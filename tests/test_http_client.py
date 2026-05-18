"""Tests for the shared HTTP client wrapper."""

from __future__ import annotations

import time

import httpx
import pytest

from licitaciones_mcp.http import RateLimiter, make_async_client
from licitaciones_mcp.http import client as http_client_module


@pytest.mark.asyncio
async def test_rate_limiter_paces_requests() -> None:
    """RateLimiter spaces out acquisitions to the configured rate."""

    limiter = RateLimiter(rate_per_sec=5.0, capacity=1.0)
    start = time.monotonic()
    for _ in range(3):
        await limiter.acquire("example.com")
    elapsed = time.monotonic() - start
    # 3 tokens at 5/s with capacity=1: first immediate, next two wait ~0.2s each.
    assert elapsed >= 0.3


@pytest.mark.asyncio
async def test_client_retries_on_500_then_succeeds() -> None:
    """The retrying client retries transient 500s and eventually returns 200."""

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] < 3:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)

    async with make_async_client(name="test", max_attempts=5) as client:
        # Swap the underlying transport with our mock.
        client._client._transport = transport  # type: ignore[attr-defined]
        response = await client.get("https://example.test/x")

    assert response.status_code == 200
    assert call_count["n"] == 3


@pytest.mark.asyncio
async def test_client_gives_up_after_max_attempts() -> None:
    """After ``max_attempts`` retries the last error response is raised."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    transport = httpx.MockTransport(handler)

    async with make_async_client(name="test", max_attempts=2) as client:
        client._client._transport = transport  # type: ignore[attr-defined]
        with pytest.raises(httpx.HTTPStatusError):
            await client.get("https://example.test/x")


@pytest.mark.asyncio
async def test_retryable_status_responses_are_closed_between_attempts() -> None:
    """Retry responses should release their connection before the next attempt."""

    responses: list[httpx.Response] = []

    def handler(request: httpx.Request) -> httpx.Response:
        response = httpx.Response(503, text="unavailable", request=request)
        responses.append(response)
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw_client:
        with pytest.raises(httpx.HTTPStatusError):
            await http_client_module.request_with_retries(
                raw_client,
                "GET",
                "https://example.test/x",
                max_attempts=2,
            )

    assert len(responses) == 2
    assert all(response.is_closed for response in responses)


@pytest.mark.asyncio
async def test_client_streams_without_prebuffering_response() -> None:
    """The retrying client exposes a streaming response context."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"chunked", request=request)

    transport = httpx.MockTransport(handler)

    async with make_async_client(name="test", max_attempts=2) as client:
        client._client._transport = transport  # type: ignore[attr-defined]
        async with client.stream("GET", "https://example.test/doc") as response:
            payload = b"".join([chunk async for chunk in response.aiter_bytes()])

    assert payload == b"chunked"


@pytest.mark.asyncio
async def test_retry_after_waits_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry-After should replace exponential backoff instead of stacking on top."""

    call_count = {"n": 0}
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "0.25"},
                request=request,
            )
        return httpx.Response(200, json={"ok": True}, request=request)

    monkeypatch.setattr(http_client_module.asyncio, "sleep", fake_sleep)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw_client:
        response = await http_client_module.request_with_retries(
            raw_client,
            "GET",
            "https://example.test/x",
            max_attempts=2,
        )

    assert response.status_code == 200
    assert sleeps == [0.25]
