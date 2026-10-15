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
    if get_settings().environment != "test":  # tests start from a pre-seeded template database
        init_db()
        from app.seed import seed_reference_data

        with SessionLocal() as db:
            seed_reference_data(db)
            if get_settings().seed_demo_on_start:
                from app.demo import seed_demo

                seed_demo(db)
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
        from app.modules.demo.api import demo_enabled

        return {"status": "ok", "environment": settings.environment, "hosting_region": settings.hosting_region, "demo_mode": demo_enabled()}

    _register_routers(app)
    if settings.serve_frontend:
        _mount_frontend(app, settings.static_dir)
    return app


def _mount_frontend(app: FastAPI, static_dir: str) -> None:
    """Serve the built portal from the API (one port). Unknown paths fall back to index.html (client routing)."""
    from pathlib import Path

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    root = Path(static_dir)
    index = root / "index.html"
    if not index.exists():
        return
    if (root / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("api/", "mock-uaepass/")):
            return JSONResponse({"error": "NOT_FOUND"}, status_code=404)
        candidate = (root / path).resolve()
        if path and candidate.is_file() and root.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
