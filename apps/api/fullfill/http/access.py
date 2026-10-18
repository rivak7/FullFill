"""One shared demo access code for ordering and kitchen screens."""

import hmac
import os

from fastapi import HTTPException, Request


def access_state(request: Request, scope="order") -> dict:
    # Keep the scope argument and role field compatible with already-open sites.
    # Both screens use the existing FULLFILL_ACCESS_KEY and have the same access.
    expected = os.getenv("FULLFILL_ACCESS_KEY", "")
    configured = bool(expected or os.getenv("VERCEL"))
    if configured and not expected:
        raise HTTPException(503, "The shared access code is not configured.")
    if not configured:
        return {"required": False, "authenticated": True, "role": "kitchen"}
    scheme, _, supplied = request.headers.get("Authorization", "").partition(" ")
    authenticated = scheme.lower() == "bearer" and hmac.compare_digest(
        supplied.encode(), expected.encode()
    )
    return {
        "required": True,
        "authenticated": authenticated,
        "role": "kitchen" if authenticated else None,
    }


def authorize(request):
    if not access_state(request)["authenticated"]:
        raise HTTPException(401, "Enter the access code.")
