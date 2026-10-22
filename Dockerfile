FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV LLM_FALLBACK_MODEL=gemini-3.6-flash
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir '.[backend,persistence,google]'
COPY backend ./backend
COPY --from=frontend /build/dist ./frontend/dist
RUN useradd --create-home finagent
USER finagent
EXPOSE 8000
CMD ["sh", "-c", "exec python -m uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
