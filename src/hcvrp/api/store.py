"""Lectura y escritura de la base de datos. Cada función de escritura confirma su transacción."""
from __future__ import annotations

import dataclasses
import json
import sqlite3
from datetime import date

from hcvrp.domain import Client, Location, LocationStatus, Order, Params, Vehicle


class ClientInUse(Exception):
    pass


class NotFound(Exception):
    pass


def _client(row: sqlite3.Row) -> Client:
    location = None if row["lat"] is None or row["lon"] is None else Location(row["lat"], row["lon"])
    return Client(row["code"], row["name"], row["address"], location, LocationStatus(row["location_status"]))


def list_clients(conn: sqlite3.Connection) -> dict[str, Client]:
    rows = conn.execute("SELECT * FROM clients ORDER BY code").fetchall()
    return {r["code"]: _client(r) for r in rows}


def get_client(conn: sqlite3.Connection, code: str) -> Client | None:
    row = conn.execute("SELECT * FROM clients WHERE code = ?", (code,)).fetchone()
    return None if row is None else _client(row)


def upsert_client(conn: sqlite3.Connection, client: Client) -> None:
    loc = client.location
    conn.execute(
        "INSERT INTO clients (code, name, address, lat, lon, location_status) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (code) DO UPDATE SET name = excluded.name, address = excluded.address, "
        "lat = excluded.lat, lon = excluded.lon, location_status = excluded.location_status",
        (
            client.code, client.name, client.address,
            loc.lat if loc else None, loc.lon if loc else None, client.location_status.value,
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
    return Order(str(row["id"]), row["client_code"], row["kg"])


def list_orders(conn: sqlite3.Connection, day: date) -> list[Order]:
    rows = conn.execute(
        "SELECT * FROM orders WHERE plan_date = ? ORDER BY client_code", (day.isoformat(),)
    ).fetchall()
    return [_order(r) for r in rows]


def add_order(conn: sqlite3.Connection, day: date, client_code: str, kg: int) -> Order:
    row = conn.execute(
        "INSERT INTO orders (plan_date, client_code, kg) VALUES (?, ?, ?) "
        "ON CONFLICT (plan_date, client_code) DO UPDATE SET kg = kg + excluded.kg RETURNING *",
        (day.isoformat(), client_code, kg),
    ).fetchone()
    conn.commit()
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


def order_day(conn: sqlite3.Connection, order_id: int) -> date | None:
    row = conn.execute("SELECT plan_date FROM orders WHERE id = ?", (order_id,)).fetchone()
    return None if row is None else date.fromisoformat(row["plan_date"])


def get_locks(conn: sqlite3.Connection, day: date) -> dict[str, tuple[str, int]]:
    rows = conn.execute(
        "SELECT l.order_id, l.vehicle_id, l.trip_no FROM locks l "
        "JOIN orders o ON o.id = l.order_id WHERE o.plan_date = ?",
        (day.isoformat(),),
    ).fetchall()
    return {str(r["order_id"]): (r["vehicle_id"], r["trip_no"]) for r in rows}


def set_lock(conn: sqlite3.Connection, order_id: int, vehicle_id: str, trip_no: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO locks (order_id, vehicle_id, trip_no) VALUES (?, ?, ?)",
        (order_id, vehicle_id, trip_no),
    )
    conn.commit()


def delete_lock(conn: sqlite3.Connection, order_id: int) -> None:
    conn.execute("DELETE FROM locks WHERE order_id = ?", (order_id,))
    conn.commit()
