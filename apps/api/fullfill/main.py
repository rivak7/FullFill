"""ASGI entry point. Routes, workers, storage, and adapters remain to be implemented."""

from fastapi import FastAPI

from .http import router


def create_app() -> FastAPI:
    app = FastAPI(
        title="FullFill",
        version="0.1.0",
        description="Scaffold only. See docs/team-development.md for unimplemented work.",
    )
    app.include_router(router)
    return app
