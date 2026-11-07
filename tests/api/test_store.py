from datetime import date

import pytest

from hcvrp.api import seed
from hcvrp.api.db import connect
from hcvrp.api.store import (
    ClientInUse, NotFound, add_order, delete_client, delete_order, get_client, get_fleet,
    clear_sequence, get_locks, get_params, get_positions, list_clients, list_orders, order_day,
    replace_orders, set_fleet, set_lock, set_params, set_sequence, update_order_kg, upsert_client,
)
from hcvrp.data.clients import load_clients, save_clients
from hcvrp.domain import DEFAULT_FLEET, Client, Location, LocationStatus, Params

D = date(2026, 10, 31)


@pytest.fixture
def conn(tmp_path):
    return connect(tmp_path / "t.db")


@pytest.fixture
def conn_with_clients(conn):
    upsert_client(conn, Client("AARON", "Aaron", "", Location(25.53, -103.40), LocationStatus.SINTETICA))
    upsert_client(conn, Client("BETO", "Beto", "", None, LocationStatus.PENDIENTE))
    return conn


def test_schema_and_defaults_empty(conn):
    assert list_clients(conn) == {}
    assert get_fleet(conn) == []
    assert get_params(conn) == Params()


def test_client_roundtrip_keeps_missing_location(conn_with_clients):
    assert get_client(conn_with_clients, "BETO") == Client("BETO", "Beto", "", None, LocationStatus.PENDIENTE)
    assert get_client(conn_with_clients, "AARON").location == Location(25.53, -103.40)
    assert get_client(conn_with_clients, "NADIE") is None


def test_add_order_same_client_sums(conn_with_clients):
    o1 = add_order(conn_with_clients, D, "AARON", 3000)
    o2 = add_order(conn_with_clients, D, "AARON", 1500)
    assert o2.order_id == o1.order_id and o2.kg == 4500
    assert len(list_orders(conn_with_clients, D)) == 1


def test_orders_are_per_day(conn_with_clients):
    o = add_order(conn_with_clients, D, "AARON", 3000)
    assert list_orders(conn_with_clients, date(2026, 11, 1)) == []
    assert order_day(conn_with_clients, int(o.order_id)) == D
    assert order_day(conn_with_clients, 999) is None


def test_update_order_kg(conn_with_clients):
    o = add_order(conn_with_clients, D, "AARON", 3000)
    assert update_order_kg(conn_with_clients, int(o.order_id), 700).kg == 700
    with pytest.raises(NotFound):
        update_order_kg(conn_with_clients, 999, 700)


def test_delete_order_cascades_lock(conn_with_clients):
    o = add_order(conn_with_clients, D, "AARON", 3000)
    set_lock(conn_with_clients, int(o.order_id), "V2", 1)
    assert get_locks(conn_with_clients, D) == {o.order_id: ("V2", 1)}
    delete_order(conn_with_clients, int(o.order_id))
    assert get_locks(conn_with_clients, D) == {}


def test_replace_orders_only_touches_that_day(conn_with_clients):
    other = add_order(conn_with_clients, date(2026, 11, 1), "AARON", 100)
    old = add_order(conn_with_clients, D, "AARON", 3000)
    set_lock(conn_with_clients, int(old.order_id), "V2", 1)
    new = replace_orders(conn_with_clients, D, [("BETO", 500)])
    assert [(o.client_code, o.kg) for o in new] == [("BETO", 500)]
    assert [(o.client_code, o.kg) for o in list_orders(conn_with_clients, D)] == [("BETO", 500)]
    assert get_locks(conn_with_clients, D) == {}
    assert list_orders(conn_with_clients, date(2026, 11, 1)) == [other]


def test_delete_client_with_orders_raises(conn_with_clients):
    add_order(conn_with_clients, D, "AARON", 3000)
    with pytest.raises(ClientInUse):
        delete_client(conn_with_clients, "AARON")
    delete_client(conn_with_clients, "BETO")
    assert get_client(conn_with_clients, "BETO") is None


def test_fleet_and_params_roundtrip(conn):
    set_fleet(conn, DEFAULT_FLEET)
    assert get_fleet(conn) == DEFAULT_FLEET
    set_fleet(conn, list(reversed(DEFAULT_FLEET)))
    assert get_fleet(conn) == list(reversed(DEFAULT_FLEET))
    set_params(conn, Params(diesel_mxn_per_liter=25.5, time_limit_s=1))
    assert get_params(conn).diesel_mxn_per_liter == 25.5


def test_seed_is_idempotent_and_cleans_null(tmp_path, clients_file):
    clients = list(load_clients(clients_file).values())
    first = clients[0]
    clients[0] = Client(first.code, first.name, "NULL", first.location, first.location_status)
    save_clients(clients, clients_file)
    db = tmp_path / "s.db"
    assert seed.main(["--clients", str(clients_file), "--db", str(db)]) == 0
    assert seed.main(["--clients", str(clients_file), "--db", str(db)]) == 0
    conn = connect(db)
    assert len(list_clients(conn)) == 35
    assert get_fleet(conn) == DEFAULT_FLEET
    assert get_client(conn, first.code).address == ""


def test_reseed_keeps_user_changes(tmp_path, clients_file):
    db = tmp_path / "s.db"
    seed.main(["--clients", str(clients_file), "--db", str(db)])
    conn = connect(db)
    fixed = Client("AARON", "Aaron", "Calle 1", Location(25.6, -103.4), LocationStatus.VERIFICADA)
    upsert_client(conn, fixed)
    set_fleet(conn, DEFAULT_FLEET[:1])
    set_params(conn, Params(diesel_mxn_per_liter=25.5))
    seed.main(["--clients", str(clients_file), "--db", str(db)])
    assert get_client(conn, "AARON") == fixed
    assert len(get_fleet(conn)) == 1
    assert get_params(conn).diesel_mxn_per_liter == 25.5


def test_lock_without_trip(conn_with_clients):
    o = add_order(conn_with_clients, D, "AARON", 3000)
    set_lock(conn_with_clients, int(o.order_id), "V2")
    assert get_locks(conn_with_clients, D) == {o.order_id: ("V2", None)}
    assert get_positions(conn_with_clients, D) == {}


def test_sequence_sets_trip_and_position_and_clears(conn_with_clients):
    a = add_order(conn_with_clients, D, "AARON", 3000)
    b = add_order(conn_with_clients, D, "BETO", 500)
    set_sequence(conn_with_clients, "V1", [[], [int(b.order_id), int(a.order_id)]])
    assert get_locks(conn_with_clients, D) == {a.order_id: ("V1", 1), b.order_id: ("V1", 1)}
    assert get_positions(conn_with_clients, D) == {b.order_id: 1, a.order_id: 2}
    set_lock(conn_with_clients, int(a.order_id), "V2")  # cambiar de camión quita la posición
    assert get_positions(conn_with_clients, D) == {b.order_id: 1}
    clear_sequence(conn_with_clients, D, "V1")
    assert get_locks(conn_with_clients, D) == {a.order_id: ("V2", None)}


def test_old_locks_table_is_migrated(tmp_path):
    import sqlite3
    path = tmp_path / "viejo.db"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE clients (code TEXT PRIMARY KEY, name TEXT NOT NULL, address TEXT NOT NULL,"
        " lat REAL, lon REAL, location_status TEXT NOT NULL);"
        "CREATE TABLE orders (id INTEGER PRIMARY KEY, plan_date TEXT NOT NULL,"
        " client_code TEXT NOT NULL REFERENCES clients(code), kg INTEGER NOT NULL,"
        " UNIQUE (plan_date, client_code));"
        "CREATE TABLE locks (order_id INTEGER PRIMARY KEY REFERENCES orders(id) ON DELETE CASCADE,"
        " vehicle_id TEXT NOT NULL, trip_no INTEGER NOT NULL);"
        "INSERT INTO clients VALUES ('AARON', 'Aaron', '', 25.5, -103.4, 'verificada');"
        f"INSERT INTO orders VALUES (1, '{D.isoformat()}', 'AARON', 3000);"
        "INSERT INTO locks VALUES (1, 'V2', 2);"
    )
    old.commit(); old.close()
    conn = connect(path)
    assert get_locks(conn, D) == {"1": ("V2", 2)}
    set_lock(conn, 1, "V3")
    assert get_locks(conn, D) == {"1": ("V3", None)}


def test_old_orders_table_gets_window_columns(tmp_path):
    import sqlite3
    path = tmp_path / "viejo2.db"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE clients (code TEXT PRIMARY KEY, name TEXT NOT NULL, address TEXT NOT NULL,"
        " lat REAL, lon REAL, location_status TEXT NOT NULL);"
        "CREATE TABLE orders (id INTEGER PRIMARY KEY, plan_date TEXT NOT NULL,"
        " client_code TEXT NOT NULL REFERENCES clients(code), kg INTEGER NOT NULL,"
        " UNIQUE (plan_date, client_code));"
        "INSERT INTO clients VALUES ('AARON', 'Aaron', '', 25.5, -103.4, 'verificada');"
        f"INSERT INTO orders VALUES (1, '{D.isoformat()}', 'AARON', 3000);"
    )
    old.commit(); old.close()
    conn = connect(path)
    (o,) = list_orders(conn, D)
    assert (o.kg, o.window_start, o.window_end) == (3000, None, None)


def test_old_clients_table_gets_default_hours(tmp_path):
    import sqlite3
    path = tmp_path / "viejo3.db"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE clients (code TEXT PRIMARY KEY, name TEXT NOT NULL, address TEXT NOT NULL,"
        " lat REAL, lon REAL, location_status TEXT NOT NULL);"
        "INSERT INTO clients VALUES ('AARON', 'Aaron', '', 25.5, -103.4, 'verificada');"
    )
    old.commit(); old.close()
    c = list_clients(connect(path))["AARON"]
    assert (c.opens_at, c.closes_at) == (9 * 60, 18 * 60)
