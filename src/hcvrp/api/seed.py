"""Carga inicial: clientes desde el JSON depurado, flota y parámetros por defecto.

Solo inserta lo que falta: volver a ejecutarlo no pisa lo que se editó en la app.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from hcvrp.api.db import connect
from hcvrp.api.settings import Settings
from hcvrp.api.store import get_client, get_fleet, set_fleet, set_params, upsert_client
from hcvrp.data.clients import load_clients
from hcvrp.domain import DEFAULT_FLEET, Params


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m hcvrp.api.seed")
    ap.add_argument("--clients", default="data/clients_laguna.json")
    ap.add_argument("--db", default=str(Settings.from_env().db_path))
    args = ap.parse_args(argv)

    conn = connect(Path(args.db))
    for client in load_clients(Path(args.clients)).values():
        if get_client(conn, client.code) is None:
            address = "" if client.address.strip() in ("", "NULL") else client.address
            upsert_client(conn, replace(client, address=address))
    if not get_fleet(conn):
        set_fleet(conn, DEFAULT_FLEET)
    if conn.execute("SELECT 1 FROM params WHERE id = 1").fetchone() is None:
        set_params(conn, Params())
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
