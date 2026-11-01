"""Rutas de pedidos, escenarios y bloqueos."""
from __future__ import annotations

import sqlite3
from datetime import date as Date

from fastapi import APIRouter, Depends, HTTPException, Request

from hcvrp.api import store
from hcvrp.api.auth import current_user, get_conn
from hcvrp.api.schemas import LockIO, OrderIn, OrderOut, OrderPatch, ScenarioIn
from hcvrp.domain import Order
from hcvrp.scenarios import SCENARIOS, generate_scenario

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def _orders_out(conn: sqlite3.Connection, day: Date, orders: list[Order]) -> list[OrderOut]:
    clients = store.list_clients(conn)
    locks = store.get_locks(conn, day)
    out = []
    for o in orders:
        lock = locks.get(o.order_id)
        out.append(OrderOut(
            id=int(o.order_id), date=day, client_code=o.client_code,
            client_name=clients[o.client_code].name, kg=o.kg,
            lock=None if lock is None else LockIO(vehicle_id=lock[0], trip_no=lock[1]),
        ))
    return out


def _day_of(conn: sqlite3.Connection, order_id: int) -> Date:
    day = store.order_day(conn, order_id)
    if day is None:
        raise HTTPException(status_code=404, detail=f"no existe el pedido {order_id}")
    return day


@router.get("/orders")
def list_orders(date: Date, conn: sqlite3.Connection = Depends(get_conn)) -> list[OrderOut]:
    return _orders_out(conn, date, store.list_orders(conn, date))


@router.post("/orders", status_code=201)
def add_order(body: OrderIn, request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> OrderOut:
    if store.get_client(conn, body.client_code) is None:
        raise HTTPException(status_code=404, detail=f"no existe el cliente {body.client_code}")
    order = store.add_order(conn, body.date, body.client_code, body.kg)
    request.app.state.on_change(body.date)
    return _orders_out(conn, body.date, [order])[0]


@router.patch("/orders/{order_id}")
def patch_order(
    order_id: int, body: OrderPatch, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> OrderOut:
    day = _day_of(conn, order_id)
    order = store.update_order_kg(conn, order_id, body.kg)
    request.app.state.on_change(day)
    return _orders_out(conn, day, [order])[0]


@router.delete("/orders/{order_id}", status_code=204)
def delete_order(order_id: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> None:
    day = _day_of(conn, order_id)
    store.delete_order(conn, order_id)
    request.app.state.on_change(day)


@router.get("/scenarios")
def list_scenarios() -> list[str]:
    return list(SCENARIOS)


@router.post("/orders/scenario")
def load_scenario(
    body: ScenarioIn, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> list[OrderOut]:
    if body.name not in SCENARIOS:
        raise HTTPException(status_code=422, detail=f"no existe el escenario {body.name}")
    try:
        generated = generate_scenario(body.name, store.list_clients(conn))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    orders = store.replace_orders(conn, body.date, [(o.client_code, o.kg) for o in generated])
    request.app.state.on_change(body.date)
    return _orders_out(conn, body.date, orders)


@router.put("/orders/{order_id}/lock")
def set_lock(
    order_id: int, body: LockIO, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> LockIO:
    day = _day_of(conn, order_id)
    if body.vehicle_id not in {v.vehicle_id for v in store.get_fleet(conn)}:
        raise HTTPException(status_code=422, detail=f"no existe el camión {body.vehicle_id}")
    max_trips = store.get_params(conn).max_trips_per_vehicle
    if body.trip_no > max_trips:
        raise HTTPException(status_code=422, detail=f"el viaje debe estar entre 1 y {max_trips}")
    store.set_lock(conn, order_id, body.vehicle_id, body.trip_no)
    request.app.state.on_change(day)
    return body


@router.delete("/orders/{order_id}/lock", status_code=204)
def delete_lock(order_id: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> None:
    day = _day_of(conn, order_id)
    store.delete_lock(conn, order_id)
    request.app.state.on_change(day)
