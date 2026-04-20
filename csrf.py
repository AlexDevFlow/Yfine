"""CSRF protection middleware for FastAPI/Starlette.

Generates a per-session CSRF token and validates it on state-changing requests
(POST, PUT, DELETE, PATCH).  The token is injected into the session and exposed
to templates via request.state.csrf_token.  JavaScript sends it back in the
X-CSRF-Token header.
"""

import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_OPEN_PREFIXES = ("/api/auth/login", "/api/settings/password-status", "/static")


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Ensure a CSRF token exists in the session
        token = request.session.get("csrf_token")
        if not token:
            token = secrets.token_hex(32)
            request.session["csrf_token"] = token

        # Make token available to templates
        request.state.csrf_token = token

        # Skip validation for safe methods
        if request.method in _SAFE_METHODS:
            return await call_next(request)

        # Skip validation for open endpoints (login must work without prior token)
        for prefix in _OPEN_PREFIXES:
            if request.url.path.startswith(prefix):
                return await call_next(request)

        # Validate CSRF token on state-changing requests
        submitted = request.headers.get("X-CSRF-Token")
        if not submitted or submitted != token:
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token missing or invalid"},
            )

        return await call_next(request)
