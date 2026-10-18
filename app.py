"""Vercel's ASGI entry point; local development still uses the app factory."""

from fullfill.main import create_app

app = create_app()
