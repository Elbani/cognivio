FROM node:22-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Build the MCP connector into a wheel so the running server can hand it to users
# (they have only the platform URL + an API key, no repo, no PyPI to install from).
FROM python:3.12-slim AS connector-build
WORKDIR /build
COPY mcp_server/ ./mcp_server/
RUN pip install --no-cache-dir build \
 && python -m build --wheel --outdir /dist ./mcp_server

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FRONTEND_DIST=/app/frontend/dist

RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser

WORKDIR /app
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Pre-download the embedding model into the image so cold starts don't fetch it at runtime
# (and the container needs no network egress to the model host). Lives under /app so the
# chown below makes it readable by appuser; the app reads the same path via this env var.
ENV FASTEMBED_CACHE_PATH=/app/.fastembed
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/app/.fastembed')"

COPY backend ./backend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
COPY --from=connector-build /dist ./connector

RUN chown -R appuser:appuser /app

USER appuser

WORKDIR /app/backend
EXPOSE 8000

# Shell form so a $PORT injected by the host is honored; falls back to 8000 locally.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
