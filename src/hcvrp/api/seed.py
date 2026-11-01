"""Carga inicial: clientes desde el JSON depurado, flota y parámetros por defecto.

Solo inserta lo que falta: volver a ejecutarlo no pisa lo que se editó en la app.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path

from hcvrp.api.db import connect
from hcvrp.api.settings import Settings, load_env
from hcvrp.api.store import (
    get_client, get_fleet, list_clients, set_fleet, set_params, upsert_client,
)
from hcvrp.data.clients import load_clients
from hcvrp.domain import DEFAULT_FLEET, LocationStatus, Params
from hcvrp.geo.ors import OrsProvider


def _snap(conn: sqlite3.Connection, ors: OrsProvider) -> None:
    """Las ubicaciones verificadas nunca se mueven; sin vía cercana, el cliente se queda donde está."""
    clients = list_clients(conn)
    points = {
        c.code: c.location for c in clients.values()
        if c.location is not None and c.location_status != LocationStatus.VERIFICADA
    }
    if not points:
        return
    for code, location in ors.snap(points).items():
        if location is not None:
            upsert_client(conn, replace(clients[code], location=location))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m hcvrp.api.seed")
    ap.add_argument("--clients", default="data/clients_laguna.json")
    ap.add_argument("--db", default=str(Settings.from_env().db_path))
    ap.add_argument("--snap", action="store_true", help="ajustar a la vía más cercana los clientes sin verificar")
    args = ap.parse_args(argv)

    ors = None
    if args.snap:
        try:
            ors = OrsProvider()
        except RuntimeError as e:
            print(e, file=sys.stderr)
            return 1

    conn = connect(Path(args.db))
    for client in load_clients(Path(args.clients)).values():
        if get_client(conn, client.code) is None:
            address = "" if client.address.strip() in ("", "NULL") else client.address
            upsert_client(conn, replace(client, address=address))
    if not get_fleet(conn):
        set_fleet(conn, DEFAULT_FLEET)
    if conn.execute("SELECT 1 FROM params WHERE id = 1").fetchone() is None:
        set_params(conn, Params())
    code = 0
    if ors is not None:
        try:
            _snap(conn, ors)
        except RuntimeError as e:
            print(e, file=sys.stderr)
            code = 1
    conn.close()
    return code


if __name__ == "__main__":
    load_env()
    raise SystemExit(main(sys.argv[1:]))
