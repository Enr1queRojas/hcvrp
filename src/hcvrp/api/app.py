"""Construcción de la app FastAPI."""
from __future__ import annotations

from fastapi import FastAPI

from hcvrp.api import routes_auth
from hcvrp.api.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="HCVRP La Laguna")
    app.state.settings = settings or Settings.from_env()
    app.state.on_change = lambda day: None
    app.include_router(routes_auth.router)
    return app
