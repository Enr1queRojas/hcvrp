"""Contraseñas, sesiones y dependencias de autenticación."""
from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import secrets
import sqlite3
import sys
import threading
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, HTTPException, Request

from hcvrp.api.db import connect
from hcvrp.api.settings import Settings

COOKIE_NAME = "hcvrp_session"
_N, _R, _P = 2**14, 8, 1


class LoginGuard:
    """Frena intentos repetidos por (usuario, IP). Vive en memoria: se limpia al reiniciar."""

    def __init__(self, max_failures: int = 5, block_s: float = 900):
        self.max_failures = max_failures
        self.block_s = block_s
        self._failures: dict[tuple[str, str], tuple[int, float]] = {}
        self._lock = threading.Lock()

    def is_blocked(self, key: tuple[str, str]) -> bool:
        with self._lock:
            count, since = self._failures.get(key, (0, 0.0))
            if time.monotonic() - since >= self.block_s:
                self._failures.pop(key, None)
                return False
            return count >= self.max_failures

    def record_failure(self, key: tuple[str, str]) -> None:
        with self._lock:
            count, _ = self._failures.get(key, (0, 0.0))
            self._failures[key] = (count + 1, time.monotonic())

    def clear(self, key: tuple[str, str]) -> None:
        with self._lock:
            self._failures.pop(key, None)


def _scrypt(pw: str, salt: bytes) -> bytes:
    return hashlib.scrypt(pw.encode(), salt=salt, n=_N, r=_R, p=_P)


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${salt.hex()}${_scrypt(pw, salt).hex()}"


def verify_password(pw: str, stored: str) -> bool:
    _, salt, digest = stored.split("$")
    return hmac.compare_digest(_scrypt(pw, bytes.fromhex(salt)).hex(), digest)


def _timestamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def create_user(conn: sqlite3.Connection, username: str, pw: str) -> None:
    """Crea el usuario; si ya existe, cambia su contraseña y cierra sus sesiones."""
    with conn:
        conn.execute(
            "INSERT INTO users (username, pw_hash) VALUES (?, ?) "
            "ON CONFLICT (username) DO UPDATE SET pw_hash = excluded.pw_hash",
            (username, hash_password(pw)),
        )
        conn.execute("DELETE FROM sessions WHERE username = ?", (username,))


def login(conn: sqlite3.Connection, username: str, pw: str, days: int) -> str | None:
    row = conn.execute("SELECT pw_hash FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        hash_password(pw)  # mismo tiempo de respuesta que con un usuario existente
        return None
    if not verify_password(pw, row["pw_hash"]):
        return None
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=days)
    conn.execute(
        "INSERT INTO sessions (token, username, expires_at) VALUES (?, ?, ?)",
        (token, username, _timestamp(expires)),
    )
    conn.commit()
    return token


def logout(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()


def user_for_token(conn: sqlite3.Connection, token: str) -> str | None:
    conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (_timestamp(datetime.now(timezone.utc)),))
    conn.commit()
    row = conn.execute("SELECT username FROM sessions WHERE token = ?", (token,)).fetchone()
    return None if row is None else row["username"]


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def current_user(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> str:
    token = request.cookies.get(COOKIE_NAME)
    username = user_for_token(conn, token) if token else None
    if username is None:
        raise HTTPException(status_code=401, detail="inicia sesión")
    return username


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m hcvrp.api.auth")
    sub = ap.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add-user", help="crear un usuario o cambiar su contraseña")
    add.add_argument("username")
    add.add_argument("--db", default=str(Settings.from_env().db_path))
    args = ap.parse_args(argv)

    pw = getpass.getpass("Contraseña: ")
    if not pw:
        print("La contraseña no puede estar vacía", file=sys.stderr)
        return 1
    if pw != getpass.getpass("Repite la contraseña: "):
        print("Las contraseñas no coinciden", file=sys.stderr)
        return 1
    conn = connect(Path(args.db))
    create_user(conn, args.username, pw)
    conn.close()
    print(f"Usuario {args.username} guardado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
