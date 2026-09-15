"""Origin check for cookie-authenticated state changes."""

from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import settings

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


async def cookie_origin_guard(request: Request, call_next):
    if (
        request.method in UNSAFE_METHODS
        and request.cookies.get("session")
        and not settings.auth_disabled
    ):
        allowed = {
            origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()
        }
        origin = request.headers.get("Origin")
        if not origin or origin not in allowed:
            return JSONResponse(status_code=403, content={"detail": "Invalid request origin"})
    return await call_next(request)
