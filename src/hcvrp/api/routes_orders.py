"""Rutas de pedidos, escenarios y bloqueos."""
from __future__ import annotations

import dataclasses
import sqlite3
from datetime import date as Date

from fastapi import APIRouter, Depends, HTTPException, Request

from hcvrp.api import store
from hcvrp.api.auth import current_user, get_conn
from hcvrp.api.planning import build_problem
from hcvrp.api.schemas import LockIO, LockOut, OrderIn, OrderOut, OrderPatch, ScenarioIn, SequenceIn
from hcvrp.domain import SHIFT_START_MIN, Client, Order, minutes_to_clock
from hcvrp.manual import manual_violations
from hcvrp.precheck import points_for
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
            window_start=o.window_start, window_end=o.window_end,
            lock=None if lock is None else LockOut(
                vehicle_id=lock[0], trip_no=lock[1], position=positions.get(o.order_id)
            ),
        ))
    return out


def _check_within_hours(client: Client, start: int | None, end: int | None) -> None:
    """Un horario de pedido no puede salirse del horario en que el cliente recibe."""
    opens = client.opens_at - SHIFT_START_MIN
    closes = client.closes_at - SHIFT_START_MIN
    if (start is not None and not opens <= start < closes) or (end is not None and not opens < end <= closes):
        raise HTTPException(
            status_code=422,
            detail=(
                f"{client.name} recibe de {minutes_to_clock(client.opens_at)} a "
                f"{minutes_to_clock(client.closes_at)}; el horario de entrega debe quedar dentro"
            ),
        )


def _check_truck_fits(conn: sqlite3.Connection, order_id: int, vehicle_id: str) -> None:
    order = store.get_order(conn, order_id)
    client = store.get_client(conn, order.client_code) if order else None
    if client is not None and not client.can_receive(vehicle_id):
        raise HTTPException(
            status_code=422, detail=f"el camión {vehicle_id} no puede entrar con {client.name}"
        )


def _check_adjustment(
    request: Request, conn: sqlite3.Connection, day: Date,
    locks: dict[str, tuple[str, int | None]], positions: dict[str, int],
) -> None:
    """Rechaza al momento, y diciendo la regla, un ajuste a mano que no se puede cumplir."""
    problem = dataclasses.replace(build_problem(conn, day), locks=locks, positions=positions)
    try:
        matrix = request.app.state.recalc.provider.matrix(points_for(problem))
    except Exception:  # sin servicio de rutas se revisa al menos la capacidad
        matrix = None
    broken = manual_violations(problem, matrix)
    if broken:
        raise HTTPException(status_code=422, detail="No se puede: " + "; ".join(broken))


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
    client = store.get_client(conn, body.client_code)
    if client is None:
        raise HTTPException(status_code=404, detail=f"no existe el cliente {body.client_code}")
    _check_within_hours(client, body.window_start, body.window_end)
    order = store.add_order(conn, body.date, body.client_code, body.kg, body.window_start, body.window_end)
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
    for order_id in ids:
        _check_truck_fits(conn, order_id, body.vehicle_id)
    locks, positions = store.get_locks(conn, body.date), store.get_positions(conn, body.date)
    for trip_no, trip in enumerate(trips, start=1):
        for position, order_id in enumerate(trip, start=1):
            locks[str(order_id)] = (body.vehicle_id, trip_no)
            positions[str(order_id)] = position
    _check_adjustment(request, conn, body.date, locks, positions)
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
    sent = body.model_fields_set
    if not sent & {"kg", "window_start", "window_end"}:
        raise HTTPException(status_code=422, detail="no hay nada que cambiar")
    if "kg" in sent:
        if body.kg is None:
            raise HTTPException(status_code=422, detail="los kilos no pueden quedar vacíos")
        order = store.update_order_kg(conn, order_id, body.kg)
    if sent & {"window_start", "window_end"}:
        current = store.get_order(conn, order_id)
        _check_within_hours(store.get_client(conn, current.client_code), body.window_start, body.window_end)
        order = store.set_order_window(conn, order_id, body.window_start, body.window_end)
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
    _check_truck_fits(conn, order_id, body.vehicle_id)
    locks, positions = store.get_locks(conn, day), store.get_positions(conn, day)
    locks[str(order_id)] = (body.vehicle_id, body.trip_no)
    positions.pop(str(order_id), None)
    _check_adjustment(request, conn, day, locks, positions)
    store.set_lock(conn, order_id, body.vehicle_id, body.trip_no)
    request.app.state.on_change(day)
    return body


@router.delete("/orders/{order_id}/lock", status_code=204)
def delete_lock(order_id: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> None:
    day = _day_of(conn, order_id)
    store.delete_lock(conn, order_id)
    request.app.state.on_change(day)
