"""Tests for the shared HTTP client wrapper."""

from __future__ import annotations

import time

import httpx
import pytest

from licitaciones_mcp.http import RateLimiter, make_async_client


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
