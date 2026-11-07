"""Rutas de pedidos, escenarios y bloqueos."""
from __future__ import annotations

import sqlite3
from datetime import date as Date

from fastapi import APIRouter, Depends, HTTPException, Request

from hcvrp.api import store
from hcvrp.api.auth import current_user, get_conn
from hcvrp.api.schemas import LockIO, LockOut, OrderIn, OrderOut, OrderPatch, ScenarioIn, SequenceIn
from hcvrp.domain import Order
from hcvrp.scenarios import SCENARIOS, generate_scenario

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def _orders_out(conn: sqlite3.Connection, day: Date, orders: list[Order]) -> list[OrderOut]:
    clients = store.list_clients(conn)
    locks = store.get_locks(conn, day)
    positions = store.get_positions(conn, day)
    out = []
    for o in orders:
        lock = locks.get(o.order_id)
        out.append(OrderOut(
            id=int(o.order_id), date=day, client_code=o.client_code,
            client_name=clients[o.client_code].name, kg=o.kg,
            lock=None if lock is None else LockOut(
                vehicle_id=lock[0], trip_no=lock[1], position=positions.get(o.order_id)
            ),
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


@router.put("/orders/sequence", status_code=204)
def set_sequence(body: SequenceIn, request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> None:
    """Fija el orden de entrega de un camión: cada pedido queda en ese camión, viaje y posición."""
    fleet = {v.vehicle_id: v for v in store.get_fleet(conn)}
    if body.vehicle_id not in fleet:
        raise HTTPException(status_code=422, detail=f"no existe el camión {body.vehicle_id}")
    if not fleet[body.vehicle_id].available:
        raise HTTPException(status_code=422, detail=f"el camión {body.vehicle_id} no está disponible")
    trips = [t for t in body.trips if t]
    ids = [i for t in trips for i in t]
    if not ids:
        raise HTTPException(status_code=422, detail="el orden no trae pedidos")
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="un pedido aparece más de una vez en el orden")
    max_trips = store.get_params(conn).max_trips_per_vehicle
    if len(trips) > max_trips:
        raise HTTPException(status_code=422, detail=f"el camión puede hacer a lo más {max_trips} viajes")
    day_ids = {int(o.order_id) for o in store.list_orders(conn, body.date)}
    missing = [i for i in ids if i not in day_ids]
    if missing:
        raise HTTPException(status_code=422, detail=f"los pedidos {missing} no son de ese día")
    store.set_sequence(conn, body.vehicle_id, trips)
    request.app.state.on_change(body.date)


@router.delete("/orders/sequence", status_code=204)
def clear_sequence(
    date: Date, vehicle_id: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> None:
    """Deja que el plan vuelva a decidir el orden de ese camión."""
    store.clear_sequence(conn, date, vehicle_id)
    request.app.state.on_change(date)


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
    if body.trip_no is not None and body.trip_no > max_trips:
        raise HTTPException(status_code=422, detail=f"el viaje debe estar entre 1 y {max_trips}")
    store.set_lock(conn, order_id, body.vehicle_id, body.trip_no)
    request.app.state.on_change(day)
    return body


@router.delete("/orders/{order_id}/lock", status_code=204)
def delete_lock(order_id: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> None:
    day = _day_of(conn, order_id)
    store.delete_lock(conn, order_id)
    request.app.state.on_change(day)
