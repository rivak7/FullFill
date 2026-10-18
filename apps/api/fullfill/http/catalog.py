"""Read and edit the shared menu within the existing demo session."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header

from fullfill.application.order_source import (
    MenuCategoryEdit,
    MenuEdit,
    MenuSnapshot,
    OrderSource,
)

from .order_source import get_order_source

router = APIRouter(prefix="/menu", tags=["catalog"])
Source = Annotated[OrderSource, Depends(get_order_source)]


@router.get("/current", response_model=MenuSnapshot)
async def current_menu(source: Source):
    return await source.menu()


@router.get("/manage", response_model=MenuSnapshot)
async def managed_menu(source: Source):
    return await source.menu()


@router.post("/items", response_model=MenuSnapshot)
async def save_item(
    edit: MenuEdit,
    source: Source,
    idempotency_key: Annotated[
        str, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    ],
):
    return await source.save_menu(edit, idempotency_key)


@router.post("/categories", response_model=MenuSnapshot)
async def add_category(
    edit: MenuCategoryEdit,
    source: Source,
    idempotency_key: Annotated[
        str, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    ],
):
    return await source.add_menu_category(edit, idempotency_key)
