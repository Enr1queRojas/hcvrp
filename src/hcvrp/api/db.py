from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    lat REAL,
    lon REAL,
    location_status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vehicles (
    vehicle_id TEXT PRIMARY KEY,
    capacity_kg INTEGER NOT NULL,
    km_per_liter REAL NOT NULL,
    available INTEGER NOT NULL,
    fixed_dispatch_cost_mxn REAL NOT NULL,
    position INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS params (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    plan_date TEXT NOT NULL,
    client_code TEXT NOT NULL REFERENCES clients(code),
    kg INTEGER NOT NULL,
    UNIQUE (plan_date, client_code)
);
CREATE TABLE IF NOT EXISTS locks (
    order_id INTEGER PRIMARY KEY REFERENCES orders(id) ON DELETE CASCADE,
    vehicle_id TEXT NOT NULL,
    trip_no INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
    plan_date TEXT PRIMARY KEY,
    inputs_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    error TEXT,
    computed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    pw_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    username TEXT NOT NULL REFERENCES users(username),
    expires_at TEXT NOT NULL
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn
