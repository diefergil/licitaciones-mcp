"""HTTP client primitives shared by source adapters.

Provides a small factory that wraps :class:`httpx.AsyncClient` with:

* per-host rate limiting via an async token bucket
* retry/backoff for transient failures (5xx, 429, network errors)
* on-disk response caching honoring ``ETag`` / ``Last-Modified`` headers

The factory returns a context manager yielding an ``httpx.AsyncClient`` so
existing source code only needs minimal changes.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

import hishel
import httpx
from hishel.httpx import AsyncCacheTransport
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from licitaciones_mcp import __version__

__all__ = [
    "RateLimiter",
    "make_async_client",
    "request_with_retries",
]


class RateLimiter:
    """Simple token-bucket rate limiter keyed per host.

    The implementation favours fairness and bounded memory over raw
    throughput: one bucket per netloc, refilled on demand.
    """

    def __init__(self, rate_per_sec: float, *, capacity: float | None = None) -> None:
        """Create a limiter targeting ``rate_per_sec`` average requests."""

        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be positive")
        self.rate = rate_per_sec
        self.capacity = float(capacity if capacity is not None else max(rate_per_sec, 1.0))
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, host: str) -> None:
        """Block until a token is available for ``host``."""

        while True:
            async with self._lock:
                tokens, last = self._buckets.get(host, (self.capacity, time.monotonic()))
                now = time.monotonic()
                tokens = min(self.capacity, tokens + (now - last) * self.rate)
                if tokens >= 1.0:
                    self._buckets[host] = (tokens - 1.0, now)
                    return
                needed = 1.0 - tokens
                wait = needed / self.rate
                self._buckets[host] = (tokens, now)
            await asyncio.sleep(wait)


_DEFAULT_USER_AGENT = (
    f"licitaciones-mcp/{__version__} (+https://github.com/diefergil/licitaciones-mcp)"
)
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class _RetryableStatus(httpx.HTTPStatusError):
    """Internal marker raised so tenacity can drive HTTP-status retries."""

    def __init__(self, response: httpx.Response) -> None:
        super().__init__(
            f"HTTP {response.status_code}", request=response.request, response=response
        )
        self.response = response


def _build_cache_storage(cache_dir: Path | None) -> hishel.AsyncBaseStorage | None:
    if cache_dir is None:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    return hishel.AsyncSqliteStorage(database_path=cache_dir / "hishel_cache.db")


@asynccontextmanager
async def make_async_client(
    *,
    name: str,
    rate_per_sec: float | None = None,
    timeout: float = 60.0,
    verify_ssl: bool = True,
    user_agent: str = _DEFAULT_USER_AGENT,
    cache_dir: Path | None = None,
    follow_redirects: bool = True,
    headers: dict[str, str] | None = None,
    max_attempts: int = 5,
) -> AsyncIterator[RetryingClient]:
    """Yield a configured ``RetryingClient`` for a named source.

    The ``name`` is only used to tag log records and rate-limit buckets; it
    does not need to be unique across processes.
    """

    storage = _build_cache_storage(cache_dir / name if cache_dir else None)
    merged_headers = {"User-Agent": user_agent}
    if headers:
        merged_headers.update(headers)

    transport: httpx.AsyncBaseTransport = httpx.AsyncHTTPTransport(verify=verify_ssl, retries=0)
    if storage is not None:
        transport = AsyncCacheTransport(next_transport=transport, storage=storage)

    limiter = RateLimiter(rate_per_sec) if rate_per_sec else None

    async with httpx.AsyncClient(
        transport=transport,
        timeout=timeout,
        headers=merged_headers,
        follow_redirects=follow_redirects,
    ) as client:
        yield RetryingClient(client=client, limiter=limiter, name=name, max_attempts=max_attempts)


class RetryingClient:
    """Thin wrapper around ``httpx.AsyncClient`` adding limiter + retries.

    Exposes ``get`` / ``post`` plus a generic ``request`` matching httpx so it
    is mostly drop-in. Retries are applied to network errors and a small set
    of transient HTTP status codes; ``Retry-After`` is honored on 429.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        limiter: RateLimiter | None,
        name: str,
        max_attempts: int = 5,
    ) -> None:
        """Wrap an existing async httpx client."""

        self._client = client
        self._limiter = limiter
        self.name = name
        self._max_attempts = max_attempts

    async def request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        """Perform a retrying request and return the final response."""

        host = urlsplit(url).netloc or self.name
        return await request_with_retries(
            self._client,
            method,
            url,
            limiter=self._limiter,
            host=host,
            max_attempts=self._max_attempts,
            **kwargs,
        )

    async def get(self, url: str, **kwargs: object) -> httpx.Response:
        """Send a GET request through the retry/limit pipeline."""

        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: object) -> httpx.Response:
        """Send a POST request through the retry/limit pipeline."""

        return await self.request("POST", url, **kwargs)


async def request_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    limiter: RateLimiter | None = None,
    host: str | None = None,
    max_attempts: int = 5,
    **kwargs: object,
) -> httpx.Response:
    """Issue an HTTP request with rate limiting and exponential backoff.

    Retries on transient network errors and on ``_RETRYABLE_STATUS`` codes.
    The ``Retry-After`` header is parsed when present on 429 responses; the
    function sleeps until the suggested time before the next attempt.
    """

    target_host = host or urlsplit(url).netloc

    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type((httpx.HTTPError, _RetryableStatus)),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1.0, min=1.0, max=30.0),
        reraise=True,
    ):
        with attempt:
            if limiter is not None:
                await limiter.acquire(target_host)
            response = await client.request(method, url, **kwargs)  # type: ignore[arg-type]
            if response.status_code in _RETRYABLE_STATUS:
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    with suppress(ValueError):
                        await asyncio.sleep(min(float(retry_after), 30.0))
                raise _RetryableStatus(response)
            return response

    # Unreachable: AsyncRetrying with reraise=True either returns or raises.
    raise RuntimeError("retry loop exited without returning a response")
