"""Small sliding-window rate limiter.

State is per process. That is enough for a single web instance; with several instances, each enforces its own
limits (move the store to Redis or Postgres if you scale out).

Limits are keyed by client IP and, for account endpoints, by email too. Campus networks can put a whole
lecture hall behind a few IPs, so per-IP limits are deliberately generous and per-account limits do the real work.
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.core.config import settings

_hits: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def reset() -> None:
    with _lock:
        _hits.clear()


def check(key: str, limit: int, window_seconds: int) -> None:
    """Record a hit for `key`; raise 429 if it exceeds `limit` within the window."""
    if not settings.rate_limit_enabled:
        return
    now = time.monotonic()
    with _lock:
        q = _hits[key]
        while q and q[0] <= now - window_seconds:
            q.popleft()
        if len(q) >= limit:
            retry = int(window_seconds - (now - q[0])) + 1
            raise HTTPException(429, "Too many requests. Please wait a bit and try again.",
                                headers={"Retry-After": str(retry)})
        q.append(now)


def client_ip(request: Request) -> str:
    # Behind a proxy, run uvicorn with --proxy-headers so request.client is the real client address.
    return request.client.host if request.client else "unknown"


def by_ip(name: str, limit: int, window_seconds: int):
    """FastAPI dependency: limit an endpoint per client IP."""
    def dependency(request: Request) -> None:
        check(f"{name}:ip:{client_ip(request)}", limit, window_seconds)
    return dependency
