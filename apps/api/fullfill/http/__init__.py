"""HTTP boundary for ordering, catalog, stations, and camera checks."""

from fastapi import APIRouter

from . import catalog, checks, orders, stations

router = APIRouter(prefix="/v1")
for component in (orders, catalog, checks, stations):
    router.include_router(component.router)
