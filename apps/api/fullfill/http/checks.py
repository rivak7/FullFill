"""TODO: checks endpoints. Contract and route plan: docs/team-development.md."""

from fastapi import APIRouter

router = APIRouter(prefix="/checks", tags=["checks"])
