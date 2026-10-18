"""Shared demo access code. Hosted deployments fail closed without a strong code."""

import hmac
import os

from fastapi import HTTPException, Request


def access_state(request: Request) -> dict[str, bool]:
    key = os.getenv("FULLFILL_ACCESS_KEY", "")
    if (os.getenv("VERCEL") and not key) or (key and len(key) < 32):
        raise HTTPException(503, "Demo access is not configured on the server.")
    authorization = request.headers.get("Authorization", "")
    scheme, _, supplied = authorization.partition(" ")
    authenticated = not key or (
        scheme.lower() == "bearer" and hmac.compare_digest(supplied.encode(), key.encode())
    )
    return {"required": bool(key), "authenticated": authenticated}


def require_menu_access(request: Request) -> None:
    key = os.getenv("FULLFILL_MENU_KEY", "")
    if len(key) < 32:
        raise HTTPException(503, "Menu editing is not configured on the server.")
    supplied = request.headers.get("X-Menu-Key", "")
    if not hmac.compare_digest(supplied.encode(), key.encode()):
        raise HTTPException(403, "Enter the menu editing code.")
