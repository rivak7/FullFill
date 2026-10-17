"""HTTP boundary. These routers intentionally have no implemented endpoints."""

from fastapi import APIRouter

from . import captures, catalog, checks, orders, stations

router = APIRouter(prefix="/v1")
for component in (orders, catalog, captures, checks, stations):
    router.include_router(component.router)
