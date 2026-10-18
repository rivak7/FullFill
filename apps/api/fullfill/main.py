"""ASGI entry point for the order entry and fulfillment screens."""

import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .adapters.orders.square import demo_menu
from .application.order_source import MenuEntry, OrderSource, OrderSourceError
from .http import router
from .http.access import access_state


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
                if not access_state(request)["authenticated"]:
                    response = JSONResponse(
                        status_code=401, content={"detail": "Enter the demo access code."}
                    )
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
    async def session(request: Request):
        return access_state(request)

    @app.get("/v1/menu", response_model=list[MenuEntry], tags=["orders"])
    async def menu():
        return demo_menu()

    app.include_router(router)
    return app
