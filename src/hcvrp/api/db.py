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
    location_status TEXT NOT NULL,
    opens_at INTEGER NOT NULL DEFAULT 540,
    closes_at INTEGER NOT NULL DEFAULT 1080,
    blocked_vehicles TEXT NOT NULL DEFAULT '[]',
    puesta INTEGER NOT NULL DEFAULT 0
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
    window_start INTEGER,
    window_end INTEGER,
    UNIQUE (plan_date, client_code)
);
CREATE TABLE IF NOT EXISTS locks (
    order_id INTEGER PRIMARY KEY REFERENCES orders(id) ON DELETE CASCADE,
    vehicle_id TEXT NOT NULL,
    trip_no INTEGER,
    position INTEGER
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
    _migrate_locks(conn)
    _migrate_order_windows(conn)
    _migrate_client_hours(conn)
    return conn


def _migrate_client_hours(conn: sqlite3.Connection) -> None:
    """BD anteriores: los clientes no tenían horario; todos quedan de 09:00 a 18:00."""
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(clients)")}
    with conn:
        if "opens_at" not in columns:
            conn.execute("ALTER TABLE clients ADD COLUMN opens_at INTEGER NOT NULL DEFAULT 540")
        if "closes_at" not in columns:
            conn.execute("ALTER TABLE clients ADD COLUMN closes_at INTEGER NOT NULL DEFAULT 1080")
        if "blocked_vehicles" not in columns:  # camiones que no pueden entrar (lista JSON)
            conn.execute("ALTER TABLE clients ADD COLUMN blocked_vehicles TEXT NOT NULL DEFAULT '[]'")
        if "puesta" not in columns:
            conn.execute("ALTER TABLE clients ADD COLUMN puesta INTEGER NOT NULL DEFAULT 0")


def _migrate_order_windows(conn: sqlite3.Connection) -> None:
    """BD anteriores: los pedidos no tenían horario de entrega."""
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(orders)")}
    with conn:
        for name in ("window_start", "window_end"):
            if name not in columns:
                conn.execute(f"ALTER TABLE orders ADD COLUMN {name} INTEGER")


def _migrate_locks(conn: sqlite3.Connection) -> None:
    """BD anteriores: trip_no era obligatorio y no había posición dentro del viaje."""
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(locks)")}
    if "position" in columns:
        return
    with conn:
        conn.execute("ALTER TABLE locks RENAME TO locks_old")
        conn.executescript(
            "CREATE TABLE locks ("
            " order_id INTEGER PRIMARY KEY REFERENCES orders(id) ON DELETE CASCADE,"
            " vehicle_id TEXT NOT NULL, trip_no INTEGER, position INTEGER);"
        )
        conn.execute(
            "INSERT INTO locks (order_id, vehicle_id, trip_no) SELECT order_id, vehicle_id, trip_no FROM locks_old"
        )
        conn.execute("DROP TABLE locks_old")
