"""Bearer-token authentication middleware for the HTTP transport.

Adds a single ``Authorization: Bearer <token>`` check to the Starlette
app returned by :meth:`FastMCP.streamable_http_app`. The token is read
from :class:`licitaciones_mcp.config.Settings` and compared in
constant time.
"""

from __future__ import annotations

import hmac

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Reject requests lacking a matching bearer token."""

    def __init__(self, app: ASGIApp, *, token: str, exempt_paths: tuple[str, ...] = ()) -> None:
        """Create the middleware with the expected token and exempt path list."""

        super().__init__(app)
        self._token = token
        self._exempt = set(exempt_paths)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Validate the ``Authorization`` header before calling the inner app."""

        if request.url.path in self._exempt:
            return await call_next(request)
        header = request.headers.get("authorization", "")
        scheme, _, value = header.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(value, self._token):
            return JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="licitaciones-mcp"'},
            )
        response: Response = await call_next(request)
        return response
