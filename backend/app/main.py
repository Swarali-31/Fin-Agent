"""Minimal FastAPI application shell."""

from __future__ import annotations

import re
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config.settings import get_settings
from backend.app.api.responses import install_exception_handlers
from backend.app.api.routes import router

settings = get_settings()
app = FastAPI(title="FinAgent API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID"],
)
app.state.workflow_tasks = {}
app.include_router(router)
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
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response
