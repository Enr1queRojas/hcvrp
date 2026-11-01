"""Construcción de la app FastAPI."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from hcvrp.api import routes_auth, routes_catalog, routes_orders, routes_plan
from hcvrp.api.planning import Recalculator, make_geometry, make_provider
from hcvrp.api.settings import Settings


def _validation_message(error: dict[str, Any]) -> str:
    if error["type"] == "value_error":
        return error["msg"].removeprefix("Value error, ")
    field = ".".join(str(part) for part in error["loc"] if part not in ("body", "query", "path"))
    return f"dato inválido en {field}"


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    messages = dict.fromkeys(_validation_message(e) for e in exc.errors())
    return JSONResponse(status_code=422, content={"detail": "; ".join(messages)})


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.recalc.request(None)  # lo que quedó sin calcular antes de apagar
    yield
    app.state.recalc.stop()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="HCVRP La Laguna", lifespan=_lifespan)
    app.state.settings = settings
    app.state.recalc = Recalculator(settings, make_provider(settings), make_geometry(settings))
    app.state.on_change = app.state.recalc.request
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.include_router(routes_auth.router)
    app.include_router(routes_catalog.router)
    app.include_router(routes_orders.router)
    app.include_router(routes_plan.router)
    return app
