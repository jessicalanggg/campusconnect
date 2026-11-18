import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import settings

log = logging.getLogger("campusconnect")


def _matcher_loop(stop: threading.Event) -> None:
    from app.matching.scheduler import run_once
    while not stop.is_set():
        try:
            run_once()
        except Exception:  # never let a failed round kill the loop
            log.exception("in-process matching round failed")
        stop.wait(settings.match_interval_minutes * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is created by Alembic migrations (not implicitly on startup).
    stop = threading.Event()
    if settings.run_matcher_in_process:
        # For hosts without background workers. Per-course advisory locks keep concurrent runs safe.
        threading.Thread(target=_matcher_loop, args=(stop,), daemon=True, name="matcher").start()
    yield
    stop.set()


app = FastAPI(title="CampusConnect API", version="1.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[s.strip() for s in settings.cors_origins.split(",") if s.strip()],
                   allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE"],
                   allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"])
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}


# Single-service deploys: serve the built React app from the same origin as the API (so session cookies are
# first-party and no CORS is needed). Mounted last so /api and /health take precedence.
if settings.static_dir and Path(settings.static_dir).is_dir():
    app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="frontend")
