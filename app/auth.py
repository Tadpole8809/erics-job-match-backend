"""Simple passcode protection for a single-user app.

If APP_PASSCODE is set in .env, every API call must send it in the
X-App-Passcode header. The app page asks for it once and remembers it on
the phone. Without APP_PASSCODE, the API is open (fine on your own computer).

Too many wrong passcodes from one address locks that address out for a while.
"""
import secrets
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from app import config

HEADER_NAME = "X-App-Passcode"
# These load without a passcode, so the app can show its passcode screen.
PUBLIC_PATHS = {"/", "/health", "/manifest.webmanifest", "/sw.js"}
MAX_FAILURES = 10
LOCKOUT_SECONDS = 15 * 60

_failures: dict[str, deque] = defaultdict(deque)

passcode_header = APIKeyHeader(
    name=HEADER_NAME,
    auto_error=False,
    description="The APP_PASSCODE from .env (only needed when it's set).",
)


def require_passcode(request: Request, supplied: str | None = Security(passcode_header)) -> None:
    expected = config.app_passcode()
    if not expected or request.url.path in PUBLIC_PATHS:
        return

    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    recent = _failures[client]
    while recent and now - recent[0] > LOCKOUT_SECONDS:
        recent.popleft()
    if len(recent) >= MAX_FAILURES:
        raise HTTPException(429, "Too many wrong passcodes. Wait 15 minutes and try again.")

    if supplied and secrets.compare_digest(supplied.encode(), expected.encode()):
        recent.clear()
        return
    if supplied:
        recent.append(now)
        raise HTTPException(401, "Wrong passcode.")
    raise HTTPException(401, "Passcode required.")
