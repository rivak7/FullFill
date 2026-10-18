"""Separate ordering and kitchen capabilities, enforced at the API boundary."""

import hmac
import os

from fastapi import HTTPException, Request

ORDER_ROUTES = {
    ("GET", "/v1/menu"),
    ("GET", "/v1/menu/current"),
    ("POST", "/v1/orders"),
    ("POST", "/v1/orders/prepare"),
}


def access_state(request: Request, scope="order") -> dict:
    ordering = os.getenv("FULLFILL_ACCESS_KEY", "")
    kitchen = os.getenv("FULLFILL_KITCHEN_KEY", "")
    configured = bool(ordering or kitchen or os.getenv("VERCEL"))
    if configured and (len(ordering) < 32 or len(kitchen) < 32 or ordering == kitchen):
        raise HTTPException(503, "Separate ordering and kitchen access codes are not configured.")
    if not configured:
        return {"required": False, "authenticated": True, "role": "kitchen"}
    scheme, _, supplied = request.headers.get("Authorization", "").partition(" ")
    role = None
    if scheme.lower() == "bearer":
        if hmac.compare_digest(supplied.encode(), kitchen.encode()):
            role = "kitchen"
        elif hmac.compare_digest(supplied.encode(), ordering.encode()):
            role = "order"
    return {
        "required": True,
        "authenticated": role == "kitchen" or (role == "order" and scope == "order"),
        "role": role,
    }


def authorize(request):
    scope = "order" if (request.method, request.url.path) in ORDER_ROUTES else "kitchen"
    session = access_state(request, scope)
    if not session["authenticated"]:
        if session["role"]:
            raise HTTPException(403, "A kitchen access code is required for this action.")
        raise HTTPException(401, "Enter the access code.")
