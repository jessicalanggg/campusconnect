# Production image: builds the React app and serves it from FastAPI on one origin
# (first-party session cookies, no CORS). Used by render.yaml; works on any Docker host.

FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Same-origin API: leave VITE_API_URL empty so the app calls /api on its own host.
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY --from=web /web/dist /app/static
ENV STATIC_DIR=/app/static \
    COOKIE_SECURE=true \
    PORT=8000
EXPOSE 8000
# --proxy-headers: behind the host's load balancer, use the real client IP (needed for rate limiting).
CMD ["sh", "-c", "alembic upgrade head && python seed.py && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
