"""ASGI entry point for the order entry and fulfillment screens."""

import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .adapters.orders.square import demo_menu
from .application.order_source import MenuEntry, OrderSource, OrderSourceError
from .http import router


def create_app(order_source: OrderSource | None = None) -> FastAPI:
    app = FastAPI(
        title="FullFill",
        version="0.1.0",
        description="Square Sandbox order entry and queue. Camera/check routes are separate work.",
    )
    app.state.order_source = order_source
    origins = [
        value.strip() for value in os.getenv("FULLFILL_WEB_ORIGINS", "").split(",") if value.strip()
    ]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "Idempotency-Key"],
        )

    @app.exception_handler(OrderSourceError)
    async def order_source_error(_request: Request, error: OrderSourceError):
        return JSONResponse(status_code=error.status_code, content={"detail": str(error)})

    @app.middleware("http")
    async def no_stale_orders(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/v1/menu", response_model=list[MenuEntry], tags=["orders"])
    async def menu():
        return demo_menu()

    app.include_router(router)
    return app
