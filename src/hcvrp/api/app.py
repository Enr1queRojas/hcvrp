"""Construcción de la app FastAPI."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from hcvrp.api import routes_auth, routes_catalog, routes_orders, routes_plan, routes_web
from hcvrp.api.auth import LoginGuard
from hcvrp.api.planning import Recalculator, make_geometry, make_provider
from hcvrp.api.settings import Settings


_FIELD_MESSAGES = {
    "date": "la fecha no es válida",
    "capacity_kg": "la capacidad debe ser mayor que 0",
    "km_per_liter": "el rendimiento debe ser mayor que 0",
    "fixed_dispatch_cost_mxn": "el costo fijo no puede ser negativo",
    "diesel_mxn_per_liter": "el precio del diésel debe ser mayor que 0",
    "loading_mxn_per_kg": "el costo de carga no puede ser negativo",
    "shift_minutes": "la jornada debe durar entre 60 y 900 minutos",
    "service_minutes": "el tiempo de entrega debe estar entre 0 y 120 minutos",
    "reload_minutes": "el tiempo de recarga debe estar entre 0 y 480 minutos",
    "max_trips_per_vehicle": "los viajes por camión deben estar entre 1 y 6",
    "time_limit_s": "el tiempo máximo de cálculo debe estar entre 1 y 60 segundos",
    "code": "el código es obligatorio, de hasta 40 caracteres y sin /",
    "name": "el nombre es obligatorio, de hasta 120 caracteres",
    "trip_no": "el viaje debe ser 1 o mayor",
}


def _validation_message(error: dict[str, Any]) -> str:
    if error["type"] == "value_error":
        return error["msg"].removeprefix("Value error, ")
    field = str(error["loc"][-1])
    return _FIELD_MESSAGES.get(field, f"dato inválido en {field}")


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
    app.state.login_guard = LoginGuard()
    app.state.recalc = Recalculator(settings, make_provider(settings), make_geometry(settings))
    app.state.on_change = app.state.recalc.request
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.include_router(routes_auth.router)
    app.include_router(routes_catalog.router)
    app.include_router(routes_orders.router)
    app.include_router(routes_plan.router)
    app.include_router(routes_web.router)
    routes_web.mount_web(app, settings.web_dist)
    return app
