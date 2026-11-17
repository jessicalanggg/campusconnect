from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes import router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is created by Alembic migrations (not implicitly on startup).
    yield

app = FastAPI(title="CampusConnect API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[s.strip() for s in settings.cors_origins.split(",")], allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])
app.include_router(router)

@app.get("/health")
def health():
    return {"status": "ok"}
