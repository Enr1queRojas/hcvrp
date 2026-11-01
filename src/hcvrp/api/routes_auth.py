"""Rutas de login."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from hcvrp.api import auth
from hcvrp.api.auth import COOKIE_NAME, current_user, get_conn

router = APIRouter(prefix="/api")


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(
    body: LoginIn, request: Request, response: Response, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, str]:
    settings = request.app.state.settings
    token = auth.login(conn, body.username, body.password, settings.session_days)
    if token is None:
        raise HTTPException(status_code=401, detail="usuario o contraseña incorrectos")
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=settings.session_days * 86_400,
        httponly=True, samesite="lax", secure=settings.cookie_secure,
    )
    return {"username": body.username}


@router.post("/logout", status_code=204, dependencies=[Depends(current_user)])
def logout(request: Request, response: Response, conn: sqlite3.Connection = Depends(get_conn)) -> None:
    settings = request.app.state.settings
    auth.logout(conn, request.cookies[COOKIE_NAME])
    response.delete_cookie(COOKIE_NAME, httponly=True, samesite="lax", secure=settings.cookie_secure)


@router.get("/me")
def me(username: str = Depends(current_user)) -> dict[str, str]:
    return {"username": username}
