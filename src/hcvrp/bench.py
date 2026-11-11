"""Banco de medición del motor: días de reparto con las restricciones del cliente.

    python -m hcvrp.bench                        # todos los casos
    python -m hcvrp.bench --only promedio        # solo los que contienen ese texto
    python -m hcvrp.bench --thorough             # a fondo: agota el límite, como el botón Recalcular
    python -m hcvrp.bench --json antes.json      # guardar, para comparar después de un cambio
    python -m hcvrp.bench --compare antes.json   # correr y mostrar la diferencia contra lo guardado

No usa datos reales: clientes sintéticos, pedidos de los escenarios y restricciones generadas con
semilla fija, así dos corridas miden lo mismo. Las restricciones se generan como las captura la
app (un horario de pedido siempre cae dentro del horario del cliente) y dejando tiempo para
descargar, para medir al motor y no pedidos imposibles por construcción.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from hcvrp.baseline import baseline_plan, served_kg
from hcvrp.cli import hhmm
from hcvrp.data.clients import synthetic_clients
from hcvrp.domain import DEFAULT_FLEET, DEPOT, SHIFT_START_MIN, Order, Params, Plan, Problem
from hcvrp.geo.matrix import HaversineProvider
from hcvrp.precheck import merge_orders
from hcvrp.scenarios import generate_scenario
from hcvrp.solver import SearchControl, solve

BIG_TRUCKS = ("Guinda", "Volvo", "Mercedes")  # los que no entran en calles angostas
SMALL_TRUCK_KG = 10_000  # lo más que carga un camión que sí entra


def _pick(rng: random.Random, items, share: float) -> list:
    items = sorted(items)
    return rng.sample(items, max(1, round(share * len(items)))) if items else []


def day(scenario: str, time_limit_s: int | None = None) -> Problem:
    """Un día de reparto: flota real, clientes sintéticos y los pedidos del escenario."""
    clients = synthetic_clients()
    params = Params() if time_limit_s is None else Params(time_limit_s=time_limit_s)
    return Problem(DEPOT, clients, list(DEFAULT_FLEET), generate_scenario(scenario, clients), params)


def with_client_hours(problem: Problem, share: float = 0.35, seed: int = 3) -> Problem:
    """Acorta el horario de recepción de una parte de los clientes con pedido."""
    rng = random.Random(seed)
    params = problem.params
    clients = dict(problem.clients)
    kg_of = {o.client_code: o.kg for o in merge_orders(problem.orders)}
    for code in _pick(rng, kg_of, share):
        unload = params.service_time(kg_of[code])
        length = max(180, unload + 90)  # al menos 3 h, y siempre con tiempo para descargar
        # Abre a una hora en punto que todavía deja descargar y volver dentro de la jornada.
        last_open = params.shift_minutes - unload - 60
        opens = rng.choice([m for m in range(0, 301, 60) if m <= max(0, last_open)])
        clients[code] = replace(
            clients[code],
            opens_at=SHIFT_START_MIN + opens,
            closes_at=min(SHIFT_START_MIN + opens + length, 20 * 60),
        )
    return replace(problem, clients=clients)


def with_order_windows(problem: Problem, share: float = 0.35, seed: int = 5) -> Problem:
    """Pone horario de entrega a una parte de los pedidos: "antes de", "desde" o ambos."""
    rng = random.Random(seed)
    params = problem.params
    picked = set(_pick(rng, [o.order_id for o in problem.orders], share))
    orders: list[Order] = []
    for o in problem.orders:
        if o.order_id in picked:
            client = problem.clients[o.client_code]
            lo = max(0, client.opens_at - SHIFT_START_MIN)
            hi = min(params.shift_minutes, client.closes_at - SHIFT_START_MIN)
            unload = params.service_time(o.kg)
            # Lo más tarde que puede empezar la descarga y aún terminar y volver.
            last_start = min(hi - unload, params.shift_minutes - unload - 60)
            kind = rng.choice(["antes", "antes", "desde", "entre"])
            start = lo + rng.choice([60, 120, 180])
            if kind == "antes" or start > last_start:
                o = replace(o, window_end=min(hi, lo + rng.choice([60, 90, 120, 180])))
            elif kind == "desde":
                o = replace(o, window_start=start)
            else:
                o = replace(o, window_start=start, window_end=min(hi, start + rng.choice([60, 120])))
        orders.append(o)
    return replace(problem, orders=orders)


def with_blocked_trucks(problem: Problem, share: float = 0.3, seed: int = 9) -> Problem:
    """A una parte de los clientes (con pedidos que caben en un camión chico) no les entran los grandes."""
    rng = random.Random(seed)
    clients = dict(problem.clients)
    small = [o.client_code for o in merge_orders(problem.orders) if o.kg <= SMALL_TRUCK_KG]
    for code in _pick(rng, small, share):
        clients[code] = replace(clients[code], blocked_vehicles=BIG_TRUCKS)
    return replace(problem, clients=clients)


def with_puesta(problem: Problem, share: float = 0.4, seed: int = 13) -> Problem:
    """Marca con puesta a una parte de los clientes con pedido."""
    rng = random.Random(seed)
    clients = dict(problem.clients)
    for code in _pick(rng, {o.client_code for o in problem.orders}, share):
        clients[code] = replace(clients[code], puesta=True)
    return replace(problem, clients=clients)


def without_truck(problem: Problem, vehicle_id: str) -> Problem:
    fleet = [replace(v, available=v.vehicle_id != vehicle_id) for v in problem.vehicles]
    return replace(problem, vehicles=fleet)


def with_everything(problem: Problem) -> Problem:
    return with_puesta(with_blocked_trucks(with_order_windows(with_client_hours(problem))))


CASES: dict[str, Callable[[Problem], Problem]] = {
    "promedio": lambda p: p,
    "promedio + horarios de clientes": with_client_hours,
    "promedio + horarios de pedidos": with_order_windows,
    "promedio + camiones que no entran": with_blocked_trucks,
    "promedio + todas las restricciones": with_everything,
    "promedio + todas, sin el Volvo": lambda p: without_truck(with_everything(p), "Volvo"),
    "normal": lambda p: p,
    "normal + todas las restricciones": with_everything,
    "pesado": lambda p: p,
    "pesado + todas las restricciones": with_everything,
}


def build(case: str, time_limit_s: int | None = None) -> Problem:
    """El problema de un caso del banco (`CASES`)."""
    return CASES[case](day(case.split(" ")[0], time_limit_s))


def measure(problem: Problem, thorough: bool = False) -> dict:
    """Resuelve un día y devuelve lo que importa: kilos, retrasos, costo y tiempos."""
    provider = HaversineProvider()
    control = SearchControl(thorough=thorough)
    started = time.perf_counter()
    plan, _ = solve(problem, provider, control=control)
    seconds = time.perf_counter() - started
    base, _ = baseline_plan(problem, provider)
    return {**_metrics(problem, plan), "seconds": round(seconds, 2),
            "seconds_to_best": round(sum(s.best_at_s for s in control.passes), 2),
            "stopped_by": "+".join(s.stopped_by for s in control.passes),
            "baseline_served_kg": served_kg(base), "baseline_cost_mxn": round(base.cost_mxn, 2)}


def _metrics(problem: Problem, plan: Plan) -> dict:
    stops = [s for v in plan.vehicles for t in v.trips for s in t.stops]
    return {
        "orders": len(merge_orders(problem.orders)),
        "ordered_kg": sum(o.kg for o in problem.orders),
        "served_kg": served_kg(plan),
        "left_orders": sum(u.kg is None for u in plan.unserved),
        "puesta_stops": sum(u.kg is not None for u in plan.unserved),
        "late_stops": sum(s.late_min > 0 for s in stops),
        "late_min": sum(s.late_min for s in stops),
        "wait_min": sum(s.wait_min for s in stops),
        "cost_mxn": round(plan.cost_mxn, 2),
        "km": round(plan.km_total, 1),
        "trucks": len(plan.vehicles),
        "reloads": plan.reloads,
        "last_return": hhmm(max((t.end_min for v in plan.vehicles for t in v.trips), default=0)),
    }


_COLUMNS = [
    ("caso", lambda c, r: c, "<"),
    ("pedidos", lambda c, r: r["orders"], ">"),
    ("kg pedidos", lambda c, r: f"{r['ordered_kg']:,}", ">"),
    ("kg entregados", lambda c, r: f"{r['served_kg']:,}", ">"),
    ("fuera", lambda c, r: r["left_orders"], ">"),
    ("puestas", lambda c, r: r["puesta_stops"], ">"),
    ("min tarde", lambda c, r: r["late_min"], ">"),
    ("costo", lambda c, r: f"{r['cost_mxn']:,.2f}", ">"),
    ("camiones", lambda c, r: r["trucks"], ">"),
    ("recargas", lambda c, r: r["reloads"], ">"),
    ("regreso", lambda c, r: r["last_return"], ">"),
    ("s al mejor", lambda c, r: f"{r['seconds_to_best']:.2f}", ">"),
    ("s total", lambda c, r: f"{r['seconds']:.2f}", ">"),
]


def render(results: dict[str, dict]) -> str:
    rows = [[str(get(case, r)) for _, get, _ in _COLUMNS] for case, r in results.items()]
    widths = [max(len(title), *(len(row[i]) for row in rows)) for i, (title, _, _) in enumerate(_COLUMNS)]
    def line(cells: list[str]) -> str:
        return "  ".join(f"{cell:{align}{width}}" for cell, width, (_, _, align) in zip(cells, widths, _COLUMNS))
    return "\n".join([line([title for title, _, _ in _COLUMNS]), *(line(row) for row in rows)])


def render_comparison(before: dict[str, dict], after: dict[str, dict]) -> str:
    """Diferencias (después - antes) en lo que importa, caso por caso."""
    lines = ["Contra la corrida guardada (después - antes):"]
    for case, new in after.items():
        old = before.get(case)
        if old is None:
            lines.append(f"  {case}: no estaba en la corrida guardada")
            continue
        lines.append(
            f"  {case}: {new['served_kg'] - old['served_kg']:+,} kg entregados, "
            f"{new['late_min'] - old['late_min']:+} min tarde, "
            f"{new['cost_mxn'] - old['cost_mxn']:+,.2f} MXN, "
            f"{new['seconds'] - old['seconds']:+.2f} s"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="python -m hcvrp.bench", description="Mide el motor en días de reparto de prueba.")
    ap.add_argument("--only", default="", help="solo los casos cuyo nombre contiene este texto")
    ap.add_argument("--time-limit", type=int, help="límite de cálculo en segundos (por omisión, el de fábrica)")
    ap.add_argument("--thorough", action="store_true", help="buscar a fondo: agotar el límite, como el botón Recalcular")
    ap.add_argument("--json", help="guardar los resultados en este archivo")
    ap.add_argument("--compare", help="comparar contra un archivo guardado con --json")
    args = ap.parse_args(argv)

    cases = [c for c in CASES if args.only.lower() in c.lower()]
    if not cases:
        print(f"ningún caso contiene {args.only!r}; casos: {', '.join(CASES)}", file=sys.stderr)
        return 2
    results: dict[str, dict] = {}
    for case in cases:
        print(f"{case}…", file=sys.stderr, flush=True)
        results[case] = measure(build(case, args.time_limit), args.thorough)
    print(render(results))
    if args.compare:
        print()
        print(render_comparison(json.loads(Path(args.compare).read_text(encoding="utf-8")), results))
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
