"""ASGI entry point for the order entry and fulfillment screens."""

import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .adapters.orders.square import demo_menu
from .application.order_source import MenuEntry, OrderSource, OrderSourceError
from .http import router
from .http.access import access_state, authorize


def create_app(order_source: OrderSource | None = None) -> FastAPI:
    app = FastAPI(
        title="FullFill",
        version="0.1.0",
        description="Square Sandbox ordering, shared kitchen queue, and browser camera checks.",
    )
    app.state.order_source = order_source
    origins = [
        value.strip() for value in os.getenv("FULLFILL_WEB_ORIGINS", "").split(",") if value.strip()
    ]

    @app.exception_handler(OrderSourceError)
    async def order_source_error(_request: Request, error: OrderSourceError):
        return JSONResponse(status_code=error.status_code, content={"detail": str(error)})

    @app.middleware("http")
    async def no_stale_orders(request: Request, call_next):
        response = None
        if (
            request.url.path.startswith("/v1/")
            and request.url.path != "/v1/session"
            and request.method != "OPTIONS"
        ):
            try:
                authorize(request)
            except HTTPException as error:
                response = JSONResponse(
                    status_code=error.status_code, content={"detail": error.detail}
                )
        if response is None:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    # CORS wraps authentication so browsers can read denied responses and preflight headers.
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        )

    @app.get("/v1/session", tags=["access"])
    async def session(request: Request, scope: Literal["order", "kitchen"] = "order"):
        return access_state(request, scope)

    @app.get("/v1/menu", response_model=list[MenuEntry], tags=["orders"])
    async def menu():
        if order_source is not None:
            return [item for item in (await order_source.menu()).items if not item.archived]
        if os.getenv("SQUARE_ACCESS_TOKEN") and os.getenv("SQUARE_LOCATION_ID"):
            from .adapters.orders.square import SquareOrders

            return [
                item for item in (await SquareOrders.from_env().menu()).items if not item.archived
            ]
        return demo_menu()

    app.include_router(router)
    return app
