"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.db import SessionLocal, init_db
from app.core.errors import PlatformError
from app.core.settings import get_settings


def _register_routers(app: FastAPI) -> None:
    from app.api import admin, auth

    app.include_router(auth.router)
    app.include_router(admin.router)
    settings = get_settings()
    if "/mock-uaepass" in settings.uaepass_issuer:
        from app.modules.identity.mock_uaepass import router as mock_router

        app.include_router(mock_router)
    # Feature modules are auto-discovered (app/modules/<name>/api.py exposing `router`).
    from app.discovery import routers

    for r in routers():
        app.include_router(r)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from app.seed import seed_reference_data

    with SessionLocal() as db:
        seed_reference_data(db)
        db.commit()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_base_url, "http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(PlatformError)
    async def _platform_error(_: Request, exc: PlatformError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.reason_code, "message": exc.message, "reference": exc.reference, "details": exc.details},
        )

    @app.get("/api/health")
    def health():
        return {"status": "ok", "environment": settings.environment, "hosting_region": settings.hosting_region}

    _register_routers(app)
    return app


app = create_app()
