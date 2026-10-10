# AI YT Studio v2 — single service: FastAPI API + built PWA frontend (PRD §7.1).
# Only the new app (backend/app + frontend/) goes into the image; the legacy app is untouched.

# ---- 1) build the frontend ----
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npx tsc --noEmit -p . && npx vite build

# ---- 2) runtime ----
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DATA_DIR=/data FRONTEND_DIST=/app/frontend/dist FFMPEG_PATH=/usr/bin/ffmpeg
# ffmpeg (Debian build includes libass + HarfBuzz/FriBidi) and Noto fonts incl. Devanagari
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-noto-core fontconfig \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements-v2.txt backend/requirements-v2.txt
RUN pip install --no-cache-dir -r backend/requirements-v2.txt
COPY backend/app backend/app
COPY --from=web /web/dist frontend/dist
RUN mkdir -p /data
EXPOSE 8000
# APP_PASSWORD and SESSION_SECRET must be provided at runtime. Provider keys are never set here.
CMD ["sh", "-c", "python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}"]
