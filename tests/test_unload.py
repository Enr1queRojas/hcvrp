"""Descarga en el cliente: dura según los kilos que se bajan (minutos por tonelada)."""
from dataclasses import replace

from hcvrp.domain import Order, UnservedReason
from hcvrp.geo.matrix import HaversineProvider
from hcvrp.schedule import build_vehicle_plan, summarize
from hcvrp.solver import solve
from hcvrp.validate import validate


def _stops(plan):
    return {s.order_id: s for v in plan.vehicles for t in v.trips for s in t.stops}


def test_stops_last_as_long_as_their_kilos(problem_for):
    p = problem_for("promedio")
    plan, m = solve(p, HaversineProvider())
    assert validate(p, plan, m) == []
    for stop in _stops(plan).values():
        assert stop.departure_min - stop.arrival_min == p.params.service_time(stop.kg)
    by_kg = sorted(_stops(plan).values(), key=lambda s: s.kg)
    small, big = by_kg[0], by_kg[-1]
    assert big.departure_min - big.arrival_min > small.departure_min - small.arrival_min


def test_a_full_big_truck_cannot_reload_and_go_again(problem_ab):
    # 20 t son 300 min de descarga: con la recarga de 120 ya no queda jornada para otro viaje.
    p = replace(problem_ab, orders=[Order("o1", "A", 20_000), Order("o2", "B", 20_000)])
    plan, m = solve(p, HaversineProvider())
    assert validate(p, plan, m) == []
    assert plan.unserved == () and plan.reloads == 0
    assert len(plan.vehicles) == 2  # un camión por pedido


def test_slower_unloading_delivers_less_on_a_saturated_day(problem_for):
    from hcvrp.baseline import served_kg

    p = problem_for("pesado")
    slow = replace(p, params=replace(p.params, unload_minutes_per_ton=30))
    assert served_kg(solve(slow, HaversineProvider())[0]) < served_kg(solve(p, HaversineProvider())[0])


def test_order_too_long_to_unload_gets_its_puesta(problem_ab):
    # 30 t caben en V4, pero a 17 min/t son 510 min de descarga: más que la jornada de 480.
    p = replace(
        problem_ab,
        orders=[Order("o1", "A", 30_000), Order("o2", "B", 4_000)],
        params=replace(problem_ab.params, unload_minutes_per_ton=17),
    )
    plan, m = solve(p, HaversineProvider())
    assert validate(p, plan, m) == []
    assert {u.order_id: u.reason for u in plan.unserved} == {"o1": UnservedReason.NO_CABE_JORNADA}

    clients = dict(p.clients)
    clients["A"] = replace(clients["A"], puesta=True)
    pp = replace(p, clients=clients)
    plan, m = solve(pp, HaversineProvider())
    assert validate(pp, plan, m) == []
    stop = _stops(plan)["o1"]
    assert stop.kg == 4_500  # 15% de 30 t
    assert stop.departure_min - stop.arrival_min == pp.params.service_time(4_500)  # lo que se baja
    rest = next(u for u in plan.unserved if u.order_id == "o1")
    assert (rest.reason, rest.kg) == (UnservedReason.PUESTA_PARCIAL, 25_500)


def test_validator_rejects_a_schedule_with_the_wrong_unloading_time(problem_ab, tiny_matrix):
    flat = replace(problem_ab.params, service_minutes=20, unload_minutes_per_ton=0)
    vp = build_vehicle_plan("V1", [problem_ab.orders], tiny_matrix, flat)  # 20 min por parada
    plan = summarize(problem_ab, [vp], [], tiny_matrix)
    violations = validate(problem_ab, plan, tiny_matrix)  # el problema pide 15 min por tonelada
    assert any("horario de parada o1 no coincide" in v for v in violations)
