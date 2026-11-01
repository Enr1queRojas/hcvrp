"""Armado del problema, cálculo del plan y recálculo en segundo plano."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
from datetime import date

from hcvrp.api import store
from hcvrp.api.db import connect
from hcvrp.api.schemas import GeometryFn, plan_out
from hcvrp.api.settings import Settings
from hcvrp.baseline import baseline_plan, compare, served_kg
from hcvrp.cli import REASONS_ES
from hcvrp.domain import DEPOT, Location, Problem
from hcvrp.geo.cache import CachedProvider
from hcvrp.geo.directions import OrsDirections, straight_line
from hcvrp.geo.matrix import DistanceProvider, HaversineProvider, Matrix
from hcvrp.geo.ors import OrsProvider
from hcvrp.solver import solve

logger = logging.getLogger(__name__)

# Mensajes de bloqueo del motor (en inglés) que pueden llegar a la pantalla.
_LOCK_MESSAGES = (
    (r"vehicle '(.+)' is unavailable", "el camión {0} no está disponible y tiene un pedido bloqueado"),
    (r"unknown vehicle '(.+)'", "el camión {0} ya no existe y tiene un pedido bloqueado"),
    (r"trip_no (\d+) outside 1\.\.(\d+)", "hay un pedido bloqueado en el viaje {0}, pero el máximo es {1}"),
)


class PlanningError(Exception):
    pass


def _in_spanish(message: str, problem: Problem) -> str:
    for pattern, text in _LOCK_MESSAGES:
        match = re.search(pattern, message)
        if match:
            return text.format(*match.groups())
    names = {o.order_id: problem.clients[o.client_code].name for o in problem.orders}
    message = re.sub(
        r"el pedido '([^']+)'", lambda m: f"el pedido de {names.get(m[1], m[1])}", message
    )
    message = re.sub(r"camión '([^']+)'", r"camión \1", message)
    for reason, label in REASONS_ES.items():
        message = message.replace(f"({reason})", f"({label})")
    return message.replace("bloqueo infeasible", "bloqueo imposible")


def build_problem(conn: sqlite3.Connection, day: date) -> Problem:
    return Problem(
        depot=DEPOT,
        clients=store.list_clients(conn),
        vehicles=store.get_fleet(conn),
        orders=store.list_orders(conn, day),
        params=store.get_params(conn),
        locks=store.get_locks(conn, day),
    )


def inputs_hash(problem: Problem, provider: str = "haversine") -> str:
    with_orders = sorted({o.client_code for o in problem.orders})
    payload = {
        "provider": provider,
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
        raise PlanningError(_in_spanish(str(e), problem)) from e
    comparison = compare(plan, baseline, problem)
    return plan_out(problem, plan, baseline, comparison, lock_cost_diff, geometry).model_dump(mode="json")


class _MissingKeyProvider:
    """Sin clave el servicio arranca igual; el fallo se ve como error del plan."""

    def __init__(self, message: str):
        self.message = message

    def matrix(self, points: dict[str, Location]) -> Matrix:
        raise RuntimeError(self.message)


def make_provider(settings: Settings) -> DistanceProvider:
    if settings.provider == "haversine":
        return HaversineProvider()
    try:
        return CachedProvider(OrsProvider())
    except RuntimeError as e:
        return _MissingKeyProvider(str(e))


def make_geometry(settings: Settings) -> GeometryFn:
    return straight_line if settings.provider == "haversine" else OrsDirections()


class Recalculator:
    """Un solo hilo que recalcula las fechas pedidas, agrupando cambios seguidos."""

    def __init__(self, settings: Settings, provider: DistanceProvider, geometry: GeometryFn | None = None):
        self.settings = settings
        self.provider = provider
        self.geometry = geometry
        self._cond = threading.Condition()
        self._pending: dict[date, tuple[float, bool]] = {}  # fecha -> (última petición, forzada)
        self._running: date | None = None
        self._stopping = False
        self._resume = threading.Event()
        self._resume.set()
        self._thread = threading.Thread(target=self._loop, name="hcvrp-recalc", daemon=True)
        self._thread.start()

    def request(self, day: date | None, force: bool = False) -> None:
        if day is None:
            conn = connect(self.settings.db_path)
            try:
                days = store.dates_with_orders(conn)
            finally:
                conn.close()
        else:
            days = [day]
        with self._cond:
            for d in days:
                forced = force or self._pending.get(d, (0.0, False))[1]
                self._pending[d] = (time.monotonic(), forced)
            self._cond.notify_all()

    def wait_idle(self, timeout: float = 60) -> bool:
        with self._cond:
            return self._cond.wait_for(lambda: not self._pending and self._running is None, timeout)

    def is_busy(self, day: date) -> bool:
        with self._cond:
            return day in self._pending or self._running == day

    def pause(self) -> None:
        self._resume.clear()

    def resume(self) -> None:
        self._resume.set()

    def stop(self) -> None:
        with self._cond:
            self._stopping = True
            self._cond.notify_all()
        self._resume.set()
        self._thread.join(timeout=5)

    def _next_due(self) -> tuple[date, bool] | None:
        """Espera a que venza el agrupamiento de alguna fecha; None si hay que detenerse."""
        with self._cond:
            while not self._stopping:
                now = time.monotonic()
                waits = {
                    d: t + self.settings.debounce_s - now for d, (t, _) in self._pending.items()
                }
                due = next((d for d, w in waits.items() if w <= 0), None)
                if due is not None:
                    _, forced = self._pending.pop(due)
                    self._running = due
                    return due, forced
                self._cond.wait(min(waits.values()) if waits else None)
        return None

    def _loop(self) -> None:
        while (job := self._next_due()) is not None:
            try:
                self._resume.wait()
                if not self._stopping:
                    self._compute(*job)
            except Exception:
                logger.exception("falló el recálculo del %s", job[0])
            finally:
                with self._cond:
                    self._running = None
                    self._cond.notify_all()

    def _compute(self, day: date, forced: bool) -> None:
        conn = connect(self.settings.db_path)
        try:
            problem = build_problem(conn, day)
            if not problem.orders:
                return
            provider = self.settings.provider
            current = inputs_hash(problem, provider)
            row = store.get_plan_row(conn, day)
            if not forced and row is not None and row["inputs_hash"] == current:
                return
            result, error = None, None
            try:
                result = run_planning(problem, self.provider, self.geometry)
            except (PlanningError, RuntimeError) as e:
                error = str(e)
            except Exception:
                logger.exception("error interno al calcular el plan del %s", day)
                error = "error interno al calcular el plan"
            if inputs_hash(build_problem(conn, day), provider) != current:
                self.request(day)
            elif error is not None:
                store.save_plan_error(conn, day, current, error)
            else:
                store.save_plan_result(conn, day, current, result)
        finally:
            conn.close()
