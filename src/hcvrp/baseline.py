"""Línea base: vecino más cercano por camión (de mayor a menor capacidad) y comparación."""
from __future__ import annotations

from dataclasses import dataclass, replace

from hcvrp.domain import Order, Plan, Problem, Unserved, UnservedReason
from hcvrp.geo.matrix import DistanceProvider, Matrix
from hcvrp.precheck import points_for, precheck
from hcvrp.schedule import DEPOT_KEY, build_vehicle_plan, summarize
from hcvrp.validate import validate


def baseline_plan(problem: Problem, provider: DistanceProvider) -> tuple[Plan, Matrix]:
    """Vecino más cercano. La línea base es por definición libre de bloqueos: ignora
    `problem.locks` y se construye y valida contra el problema sin ellos."""
    problem = replace(problem, locks={}, positions={})
    matrix = provider.matrix(points_for(problem))
    pending, unserved = precheck(problem, matrix)
    params = problem.params
    trucks = sorted((v for v in problem.vehicles if v.available), key=lambda v: -v.capacity_kg)

    vehicle_plans = []
    for truck in trucks:
        trips: list[list[Order]] = []
        start = 0
        while pending and len(trips) < params.max_trips_per_vehicle:
            pos, t, load = DEPOT_KEY, start, 0
            trip: list[Order] = []
            while True:
                best = None
                for o in pending:
                    if load + o.kg > truck.capacity_kg:
                        continue
                    go = matrix.minutes(pos, o.client_code)
                    back = matrix.minutes(o.client_code, DEPOT_KEY)
                    if t + go + params.service_minutes + back > params.shift_minutes:
                        continue
                    if best is None or go < best[0]:
                        best = (go, o)
                if best is None:
                    break
                go, o = best
                trip.append(o)
                pending.remove(o)
                load += o.kg
                t += go + params.service_minutes
                pos = o.client_code
            if not trip:
                break
            trips.append(trip)
            start = t + matrix.minutes(pos, DEPOT_KEY) + params.reload_minutes
        vehicle_plans.append(build_vehicle_plan(truck.vehicle_id, trips, matrix, params))

    unserved = unserved + [Unserved(o.order_id, UnservedReason.SATURACION_FLOTA) for o in pending]
    plan = summarize(problem, vehicle_plans, unserved, matrix)
    violations = validate(problem, plan, matrix)
    if violations:
        raise AssertionError("línea base inválida:\n" + "\n".join(violations))
    return plan, matrix


@dataclass(frozen=True)
class Comparison:
    served_kg_diff: int
    cost_diff_mxn: float
    optimized_is_better_or_equal: bool


def served_kg(plan: Plan) -> int:
    return sum(t.kg for v in plan.vehicles for t in v.trips)


def compare(optimized: Plan, baseline: Plan, problem: Problem) -> Comparison:
    kg_diff = served_kg(optimized) - served_kg(baseline)
    cost_diff = optimized.cost_mxn - baseline.cost_mxn
    better = kg_diff > 0 or (kg_diff == 0 and cost_diff <= 0.01)
    return Comparison(kg_diff, cost_diff, better)
