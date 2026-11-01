"""Rutas del plan."""
from __future__ import annotations

import sqlite3
from datetime import date as Date

from fastapi import APIRouter, Depends, Request

from hcvrp.api import store
from hcvrp.api.auth import current_user, get_conn
from hcvrp.api.planning import build_problem, inputs_hash
from hcvrp.api.schemas import PlanStatusOut

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


@router.get("/plan")
def get_plan(date: Date, request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> PlanStatusOut:
    row = store.get_plan_row(conn, date)
    problem = build_problem(conn, date)
    if row is None and not problem.orders:
        return PlanStatusOut(status="ninguno", stale=False, error=None, plan=None, computed_at=None)

    provider = request.app.state.settings.provider
    current = row is not None and row["inputs_hash"] == inputs_hash(problem, provider)
    if not problem.orders:
        status = row["status"]
    elif request.app.state.recalc.is_busy(date) or not current:
        status = "calculando"
    else:
        status = row["status"]

    plan = row["result"] if row else None
    # Un plan guardado junto a un error es el último bueno: corresponde a datos anteriores.
    stale = plan is not None and (not current or row["status"] == "error")
    return PlanStatusOut(
        status=status,
        stale=stale,
        error=row["error"] if status == "error" else None,
        plan=plan,
        computed_at=row["computed_at"] if row else None,
    )


@router.post("/plan/recalcular", status_code=202)
def recalculate(date: Date, request: Request) -> dict[str, str]:
    request.app.state.recalc.request(date, force=True)
    return {"status": "calculando"}
