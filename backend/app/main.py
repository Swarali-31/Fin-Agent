"""Minimal FastAPI application shell."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config.settings import get_settings
from backend.app.api.responses import install_exception_handlers
from backend.app.api.routes import router
from backend.app.auth.routes import router as auth_router, authenticate
from backend.app.services.api import APIServiceError
from backend.app.api.responses import _error_response
from backend.app.repositories.base import PersistenceNotConfigured

settings = get_settings()
app = FastAPI(title="FinAgent API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID"],
)
app.state.workflow_tasks = {}
app.include_router(router)
app.include_router(auth_router)
install_exception_handlers(app)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next) -> Response:
    supplied_id = request.headers.get("X-Request-ID", "")
    request_id = (
        supplied_id
        if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", supplied_id)
        else str(uuid4())
    )
    request.state.request_id = request_id
    if request.url.path.startswith("/api/v1/") and request.method != "OPTIONS":
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD"} and origin and origin not in settings.cors_origins:
            return _error_response(request, 403, "origin_not_allowed", "Request origin is not allowed.", None)
        public = {"/api/v1/health", "/api/v1/agents", "/api/v1/auth/signup", "/api/v1/auth/login", "/api/v1/auth/me", "/api/v1/auth/setup", "/api/v1/auth/logout"}
        if request.url.path not in public:
            try:
                user = await run_in_threadpool(authenticate, request)
                if not user:
                    return _error_response(request, 401, "authentication_required", "Sign in to access your workspace.", None)
                request.state.user = user
            except SQLAlchemyError:
                return _error_response(request, 503, "database_unavailable", "Your workspace database is unavailable. Please try again shortly.", None)
            except PersistenceNotConfigured as exc:
                return _error_response(request, 503, exc.code, str(exc), None)
            except APIServiceError as exc:
                return _error_response(request, exc.status_code, exc.code, str(exc), None)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# Serve the built React app from the same origin as API/session cookies.

_frontend = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if (_frontend / "index.html").is_file():
    @app.get("/sample-expenses.csv", include_in_schema=False)
    async def sample_expenses():
        return FileResponse(_frontend / "sample-expenses.csv", media_type="text/csv", filename="FinAgent_SAMPLE_expenses.csv")

    app.mount("/assets", StaticFiles(directory=_frontend / "assets"), name="assets")

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def frontend_page(path: str):
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Endpoint not found.")
        return FileResponse(_frontend / "index.html", headers={"Cache-Control": "no-cache"})
