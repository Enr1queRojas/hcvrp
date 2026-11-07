"""Lectura y escritura de la base de datos. Cada función de escritura confirma su transacción."""
from __future__ import annotations

import dataclasses
import json
import sqlite3
from datetime import date, datetime, timezone

from hcvrp.domain import Client, Location, LocationStatus, Order, Params, Vehicle


class ClientInUse(Exception):
    pass


class NotFound(Exception):
    pass


def _client(row: sqlite3.Row) -> Client:
    location = None if row["lat"] is None or row["lon"] is None else Location(row["lat"], row["lon"])
    return Client(
        row["code"], row["name"], row["address"], location, LocationStatus(row["location_status"]),
        row["opens_at"], row["closes_at"], tuple(json.loads(row["blocked_vehicles"])), bool(row["puesta"]),
    )


def list_clients(conn: sqlite3.Connection) -> dict[str, Client]:
    rows = conn.execute("SELECT * FROM clients ORDER BY code").fetchall()
    return {r["code"]: _client(r) for r in rows}


def get_client(conn: sqlite3.Connection, code: str) -> Client | None:
    row = conn.execute("SELECT * FROM clients WHERE code = ?", (code,)).fetchone()
    return None if row is None else _client(row)


def upsert_client(conn: sqlite3.Connection, client: Client) -> None:
    loc = client.location
    conn.execute(
        "INSERT INTO clients (code, name, address, lat, lon, location_status, opens_at, closes_at, "
        "blocked_vehicles, puesta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (code) DO UPDATE SET name = excluded.name, address = excluded.address, "
        "lat = excluded.lat, lon = excluded.lon, location_status = excluded.location_status, "
        "opens_at = excluded.opens_at, closes_at = excluded.closes_at, "
        "blocked_vehicles = excluded.blocked_vehicles, puesta = excluded.puesta",
        (
            client.code, client.name, client.address,
            loc.lat if loc else None, loc.lon if loc else None, client.location_status.value,
            client.opens_at, client.closes_at, json.dumps(list(client.blocked_vehicles)), int(client.puesta),
        ),
    )
    conn.commit()


def delete_client(conn: sqlite3.Connection, code: str) -> None:
    if conn.execute("SELECT 1 FROM orders WHERE client_code = ? LIMIT 1", (code,)).fetchone():
        raise ClientInUse(code)
    conn.execute("DELETE FROM clients WHERE code = ?", (code,))
    conn.commit()


def get_fleet(conn: sqlite3.Connection) -> list[Vehicle]:
    rows = conn.execute("SELECT * FROM vehicles ORDER BY position").fetchall()
    return [
        Vehicle(
            r["vehicle_id"], r["capacity_kg"], r["km_per_liter"],
            bool(r["available"]), r["fixed_dispatch_cost_mxn"],
        )
        for r in rows
    ]


def set_fleet(conn: sqlite3.Connection, vehicles: list[Vehicle]) -> None:
    with conn:
        conn.execute("DELETE FROM vehicles")
        conn.executemany(
            "INSERT INTO vehicles (vehicle_id, capacity_kg, km_per_liter, available, "
            "fixed_dispatch_cost_mxn, position) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (v.vehicle_id, v.capacity_kg, v.km_per_liter, int(v.available), v.fixed_dispatch_cost_mxn, i)
                for i, v in enumerate(vehicles)
            ],
        )


def get_params(conn: sqlite3.Connection) -> Params:
    row = conn.execute("SELECT json FROM params WHERE id = 1").fetchone()
    return Params() if row is None else Params(**json.loads(row["json"]))


def set_params(conn: sqlite3.Connection, params: Params) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO params (id, json) VALUES (1, ?)",
        (json.dumps(dataclasses.asdict(params)),),
    )
    conn.commit()


def _order(row: sqlite3.Row) -> Order:
    return Order(str(row["id"]), row["client_code"], row["kg"], row["window_start"], row["window_end"])


def list_orders(conn: sqlite3.Connection, day: date) -> list[Order]:
    rows = conn.execute(
        "SELECT * FROM orders WHERE plan_date = ? ORDER BY client_code", (day.isoformat(),)
    ).fetchall()
    return [_order(r) for r in rows]


def add_order(
    conn: sqlite3.Connection,
    day: date,
    client_code: str,
    kg: int,
    window_start: int | None = None,
    window_end: int | None = None,
) -> Order:
    """Si el cliente ya tiene pedido ese día, suma los kilos; un horario nuevo reemplaza al anterior."""
    row = conn.execute(
        "INSERT INTO orders (plan_date, client_code, kg, window_start, window_end) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT (plan_date, client_code) DO UPDATE SET kg = kg + excluded.kg, "
        "window_start = CASE WHEN excluded.window_start IS NULL AND excluded.window_end IS NULL "
        "  THEN window_start ELSE excluded.window_start END, "
        "window_end = CASE WHEN excluded.window_start IS NULL AND excluded.window_end IS NULL "
        "  THEN window_end ELSE excluded.window_end END "
        "RETURNING *",
        (day.isoformat(), client_code, kg, window_start, window_end),
    ).fetchone()
    conn.commit()
    return _order(row)


def set_order_window(
    conn: sqlite3.Connection, order_id: int, window_start: int | None, window_end: int | None
) -> Order:
    row = conn.execute(
        "UPDATE orders SET window_start = ?, window_end = ? WHERE id = ? RETURNING *",
        (window_start, window_end, order_id),
    ).fetchone()
    conn.commit()
    if row is None:
        raise NotFound(order_id)
    return _order(row)


def update_order_kg(conn: sqlite3.Connection, order_id: int, kg: int) -> Order:
    row = conn.execute("UPDATE orders SET kg = ? WHERE id = ? RETURNING *", (kg, order_id)).fetchone()
    conn.commit()
    if row is None:
        raise NotFound(order_id)
    return _order(row)


def delete_order(conn: sqlite3.Connection, order_id: int) -> None:
    conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    conn.commit()


def replace_orders(conn: sqlite3.Connection, day: date, orders: list[tuple[str, int]]) -> list[Order]:
    with conn:
        conn.execute("DELETE FROM orders WHERE plan_date = ?", (day.isoformat(),))
        conn.executemany(
            "INSERT INTO orders (plan_date, client_code, kg) VALUES (?, ?, ?) "
            "ON CONFLICT (plan_date, client_code) DO UPDATE SET kg = kg + excluded.kg",
            [(day.isoformat(), code, kg) for code, kg in orders],
        )
    return list_orders(conn, day)


def get_order(conn: sqlite3.Connection, order_id: int) -> Order | None:
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return None if row is None else _order(row)


def order_day(conn: sqlite3.Connection, order_id: int) -> date | None:
    row = conn.execute("SELECT plan_date FROM orders WHERE id = ?", (order_id,)).fetchone()
    return None if row is None else date.fromisoformat(row["plan_date"])


def _lock_rows(conn: sqlite3.Connection, day: date) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT l.order_id, l.vehicle_id, l.trip_no, l.position FROM locks l "
        "JOIN orders o ON o.id = l.order_id WHERE o.plan_date = ?",
        (day.isoformat(),),
    ).fetchall()


def get_locks(conn: sqlite3.Connection, day: date) -> dict[str, tuple[str, int | None]]:
    return {str(r["order_id"]): (r["vehicle_id"], r["trip_no"]) for r in _lock_rows(conn, day)}


def get_positions(conn: sqlite3.Connection, day: date) -> dict[str, int]:
    return {
        str(r["order_id"]): r["position"]
        for r in _lock_rows(conn, day)
        if r["position"] is not None and r["trip_no"] is not None
    }


def set_lock(conn: sqlite3.Connection, order_id: int, vehicle_id: str, trip_no: int | None = None) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO locks (order_id, vehicle_id, trip_no, position) VALUES (?, ?, ?, NULL)",
        (order_id, vehicle_id, trip_no),
    )
    conn.commit()


def set_sequence(conn: sqlite3.Connection, vehicle_id: str, trips: list[list[int]]) -> None:
    """Fija camión, viaje y posición de cada pedido según el orden dado (viajes vacíos se omiten)."""
    rows = [
        (order_id, vehicle_id, trip_no, position)
        for trip_no, trip in enumerate((t for t in trips if t), start=1)
        for position, order_id in enumerate(trip, start=1)
    ]
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO locks (order_id, vehicle_id, trip_no, position) VALUES (?, ?, ?, ?)",
            rows,
        )


def clear_sequence(conn: sqlite3.Connection, day: date, vehicle_id: str) -> None:
    """Quita los bloqueos con orden a mano de ese camión en ese día."""
    with conn:
        conn.execute(
            "DELETE FROM locks WHERE vehicle_id = ? AND position IS NOT NULL AND order_id IN "
            "(SELECT id FROM orders WHERE plan_date = ?)",
            (vehicle_id, day.isoformat()),
        )


def delete_lock(conn: sqlite3.Connection, order_id: int) -> None:
    conn.execute("DELETE FROM locks WHERE order_id = ?", (order_id,))
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_plan_row(conn: sqlite3.Connection, day: date) -> dict | None:
    row = conn.execute("SELECT * FROM plans WHERE plan_date = ?", (day.isoformat(),)).fetchone()
    if row is None:
        return None
    return {
        "inputs_hash": row["inputs_hash"],
        "status": row["status"],
        "result": None if row["result_json"] is None else json.loads(row["result_json"]),
        "error": row["error"],
        "computed_at": row["computed_at"],
    }


def save_plan_result(conn: sqlite3.Connection, day: date, inputs_hash: str, result: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO plans (plan_date, inputs_hash, status, result_json, error, computed_at) "
        "VALUES (?, ?, 'listo', ?, NULL, ?)",
        (day.isoformat(), inputs_hash, json.dumps(result), _now()),
    )
    conn.commit()


def save_plan_error(conn: sqlite3.Connection, day: date, inputs_hash: str, message: str) -> None:
    """Guarda el error y conserva el último resultado bueno."""
    conn.execute(
        "INSERT INTO plans (plan_date, inputs_hash, status, result_json, error, computed_at) "
        "VALUES (?, ?, 'error', NULL, ?, ?) "
        "ON CONFLICT (plan_date) DO UPDATE SET inputs_hash = excluded.inputs_hash, "
        "status = 'error', error = excluded.error, computed_at = excluded.computed_at",
        (day.isoformat(), inputs_hash, message, _now()),
    )
    conn.commit()


def dates_with_orders(conn: sqlite3.Connection) -> list[date]:
    rows = conn.execute("SELECT DISTINCT plan_date FROM orders ORDER BY plan_date").fetchall()
    return [date.fromisoformat(r["plan_date"]) for r in rows]
