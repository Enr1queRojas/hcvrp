"""Armado del problema, cálculo del plan y recálculo en segundo plano."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import sqlite3
from datetime import date

from hcvrp.api import store
from hcvrp.api.schemas import GeometryFn, plan_out
from hcvrp.baseline import baseline_plan, compare, served_kg
from hcvrp.domain import DEPOT, Problem
from hcvrp.geo.matrix import DistanceProvider
from hcvrp.solver import solve

# Mensajes de bloqueo del motor (en inglés) que pueden llegar a la pantalla.
_LOCK_MESSAGES = (
    (r"vehicle '(.+)' is unavailable", "el camión {0} no está disponible y tiene un pedido bloqueado"),
    (r"unknown vehicle '(.+)'", "el camión {0} ya no existe y tiene un pedido bloqueado"),
    (r"trip_no (\d+) outside 1\.\.(\d+)", "hay un pedido bloqueado en el viaje {0}, pero el máximo es {1}"),
)


class PlanningError(Exception):
    pass


def _in_spanish(message: str) -> str:
    for pattern, text in _LOCK_MESSAGES:
        match = re.search(pattern, message)
        if match:
            return text.format(*match.groups())
    return message


def build_problem(conn: sqlite3.Connection, day: date) -> Problem:
    return Problem(
        depot=DEPOT,
        clients=store.list_clients(conn),
        vehicles=store.get_fleet(conn),
        orders=store.list_orders(conn, day),
        params=store.get_params(conn),
        locks=store.get_locks(conn, day),
    )


def inputs_hash(problem: Problem) -> str:
    with_orders = sorted({o.client_code for o in problem.orders})
    payload = {
        "depot": dataclasses.asdict(problem.depot),
        "clients": [dataclasses.asdict(problem.clients[code]) for code in with_orders],
        "vehicles": [dataclasses.asdict(v) for v in problem.vehicles],
        "orders": [dataclasses.asdict(o) for o in problem.orders],
        "params": dataclasses.asdict(problem.params),
        "locks": problem.locks,
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def run_planning(problem: Problem, provider: DistanceProvider, geometry: GeometryFn | None = None) -> dict:
    try:
        plan, _ = solve(problem, provider)
        baseline, _ = baseline_plan(problem, provider)
        lock_cost_diff = None
        if problem.locks:
            free, _ = solve(dataclasses.replace(problem, locks={}), provider)
            lock_cost_diff = plan.cost_mxn - free.cost_mxn
            # Con tiempo limitado el plan libre puede salir peor que el bloqueado.
            if served_kg(plan) == served_kg(free):
                lock_cost_diff = max(lock_cost_diff, 0.0)
    except ValueError as e:
        raise PlanningError(_in_spanish(str(e))) from e
    comparison = compare(plan, baseline, problem)
    return plan_out(problem, plan, baseline, comparison, lock_cost_diff, geometry).model_dump(mode="json")
