"""Rutas de clientes, flota y parámetros."""
from __future__ import annotations

import sqlite3
from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException, Request

from hcvrp.api import store
from hcvrp.api.auth import current_user, get_conn
from hcvrp.api.schemas import ClientIn, ClientOut, ClientPatch, LocationIn, ParamsIO, VehicleIO
from hcvrp.domain import Client, Location, LocationStatus, Params, Vehicle, clock_to_minutes

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def _existing(conn: sqlite3.Connection, code: str) -> Client:
    client = store.get_client(conn, code)
    if client is None:
        raise HTTPException(status_code=404, detail=f"no existe el cliente {code}")
    return client


@router.get("/clients")
def list_clients(conn: sqlite3.Connection = Depends(get_conn)) -> list[ClientOut]:
    return [ClientOut.of(c) for c in store.list_clients(conn).values()]


@router.post("/clients", status_code=201)
def create_client(
    body: ClientIn, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> ClientOut:
    if store.get_client(conn, body.code) is not None:
        raise HTTPException(status_code=409, detail=f"ya existe el cliente {body.code}")
    client = Client(
        body.code, body.name, body.address, None, LocationStatus.PENDIENTE,
        clock_to_minutes(body.opens_at), clock_to_minutes(body.closes_at),
    )
    store.upsert_client(conn, client)
    request.app.state.on_change(None)
    return ClientOut.of(client)


@router.patch("/clients/{code}")
def patch_client(
    code: str, body: ClientPatch, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> ClientOut:
    changes = body.model_dump(exclude_none=True)
    for field in ("opens_at", "closes_at"):
        if field in changes:
            changes[field] = clock_to_minutes(changes[field])
    try:
        client = replace(_existing(conn, code), **changes)
    except ValueError:
        raise HTTPException(status_code=422, detail="el horario del cliente debe abrir antes de cerrar") from None
    store.upsert_client(conn, client)
    request.app.state.on_change(None)
    return ClientOut.of(client)


@router.put("/clients/{code}/location")
def set_location(
    code: str, body: LocationIn, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> ClientOut:
    client = replace(
        _existing(conn, code),
        location=Location(body.lat, body.lon),
        location_status=LocationStatus.VERIFICADA,
    )
    store.upsert_client(conn, client)
    request.app.state.on_change(None)
    return ClientOut.of(client)


@router.delete("/clients/{code}", status_code=204)
def delete_client(code: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> None:
    _existing(conn, code)
    try:
        store.delete_client(conn, code)
    except store.ClientInUse:
        raise HTTPException(
            status_code=409, detail=f"el cliente {code} tiene pedidos; bórralos primero"
        ) from None
    request.app.state.on_change(None)


@router.get("/fleet")
def get_fleet(conn: sqlite3.Connection = Depends(get_conn)) -> list[VehicleIO]:
    return [VehicleIO.model_validate(v) for v in store.get_fleet(conn)]


@router.put("/fleet")
def put_fleet(
    body: list[VehicleIO], request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> list[VehicleIO]:
    if not body:
        raise HTTPException(status_code=422, detail="la flota no puede quedar vacía")
    ids = [v.vehicle_id for v in body]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="hay camiones con el mismo identificador")
    store.set_fleet(conn, [Vehicle(**v.model_dump()) for v in body])
    request.app.state.on_change(None)
    return body


@router.get("/params")
def get_params(conn: sqlite3.Connection = Depends(get_conn)) -> ParamsIO:
    return ParamsIO.model_validate(store.get_params(conn))


@router.put("/params")
def put_params(
    body: ParamsIO, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> ParamsIO:
    store.set_params(conn, Params(**body.model_dump()))
    request.app.state.on_change(None)
    return body
