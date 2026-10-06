from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .config import settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        h["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        h["Cache-Control"] = (
            "no-store"  # evidence and personal data must never be cached
        )
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if settings.cookie_secure:
            h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response
