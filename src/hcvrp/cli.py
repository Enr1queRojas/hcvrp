from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from hcvrp.baseline import baseline_plan, compare, served_kg
from hcvrp.data.clients import load_clients
from hcvrp.domain import DEFAULT_FLEET, DEPOT, Params, Plan, Problem
from hcvrp.geo.cache import CachedProvider
from hcvrp.geo.matrix import HaversineProvider
from hcvrp.geo.ors import OrsProvider
from hcvrp.scenarios import SCENARIOS, generate_scenario
from hcvrp.solver import solve

REASONS_ES = {
    "excede_capacidad": "excede la capacidad de todos los camiones",
    "no_cabe_jornada": "no cabe en la jornada",
    "fuera_horario_cliente": "no cabe dentro del horario en que recibe el cliente",
    "ningun_camion_entra": "ningún camión disponible puede entrar con el cliente",
    "puesta_parcial": "puesta: hoy se entregó una parte, el resto pasa a otro día",
    "sin_coordenadas": "cliente sin coordenadas",
    "saturacion_flota": "saturación de la flota",
}


def hhmm(minute: int) -> str:
    total = 9 * 60 + minute
    return f"{total // 60:02d}:{total % 60:02d}"


def _summary(title: str, plan: Plan) -> list[str]:
    return [
        f"{title}: costo ${plan.cost_mxn:,.2f} MXN, {plan.km_total:.1f} km, "
        f"{plan.liters_total:.1f} L, {plan.reloads} recargas, {len(plan.vehicles)} camiones, "
        f"{served_kg(plan):,} kg entregados"
    ]


def render(problem: Problem, plan: Plan, base: Plan) -> str:
    lines: list[str] = ["== Resumen =="]
    lines += _summary("Plan optimizado", plan)
    lines.append("")
    lines.append("== Carga de esta tarde (viaje 1 de cada camión) ==")
    for vp in plan.vehicles:
        first = vp.trips[0]
        lines.append(f"{vp.vehicle_id}: {first.kg:,} kg, {len(first.stops)} clientes")
    lines.append("")
    lines.append("== Viajes ==")
    for vp in plan.vehicles:
        for t in vp.trips:
            lines.append(
                f"{vp.vehicle_id} viaje {t.trip_no}: {hhmm(t.start_min)}-{hhmm(t.end_min)}, "
                f"{t.kg:,} kg, {t.km:.1f} km"
            )
            for s in t.stops:
                name = problem.clients[s.client_code].name
                lines.append(
                    f"    {hhmm(s.arrival_min)} {s.client_code} {name} ({s.kg:,} kg) sale {hhmm(s.departure_min)}"
                )
    lines.append("")
    lines.append("== No servidos ==")
    if plan.unserved:
        for u in plan.unserved:
            lines.append(f"{u.order_id}: {REASONS_ES.get(str(u.reason), str(u.reason))} ({u.reason})")
    else:
        lines.append("ninguno")
    if plan.uses_unverified_locations:
        lines.append("")
        lines.append("AVISO: el plan usa ubicaciones no verificadas (coordenadas sintéticas o pendientes).")
    lines.append("")
    lines.append("== Línea base (vecino más cercano) ==")
    lines += _summary("Línea base", base)
    c = compare(plan, base, problem)
    lines.append(
        f"Diferencia (optimizado - base): {c.served_kg_diff:+,} kg entregados, "
        f"{c.cost_diff_mxn:+,.2f} MXN; optimizado "
        f"{'mejor o igual' if c.optimized_is_better_or_equal else 'peor'}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="hcvrp")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("solve", help="planear la ruta de la tarde")
    s.add_argument("--scenario", required=True, choices=list(SCENARIOS))
    s.add_argument("--provider", choices=["haversine", "ors"], default="haversine")
    s.add_argument("--clients", default="data/clients_laguna.json")
    s.add_argument("--out")
    args = ap.parse_args(argv)

    clients = load_clients(Path(args.clients))
    problem = Problem(
        DEPOT, clients, list(DEFAULT_FLEET), generate_scenario(args.scenario, clients), Params()
    )
    provider = HaversineProvider() if args.provider == "haversine" else CachedProvider(OrsProvider())
    plan, _ = solve(problem, provider)
    base, _ = baseline_plan(problem, provider)
    print(render(problem, plan, base))
    if args.out:
        Path(args.out).write_text(
            json.dumps(dataclasses.asdict(plan), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
