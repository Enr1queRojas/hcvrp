"""Ajustes a mano: se rechazan diciendo la regla exacta y no revuelven lo que no se tocó."""
from dataclasses import replace

import pytest

from hcvrp.domain import Order
from hcvrp.geo.matrix import HaversineProvider
from hcvrp.manual import anchored_routes, manual_violations
from hcvrp.precheck import points_for
from hcvrp.solver import SearchControl, solve
from hcvrp.validate import validate


def _routes(plan):
    return {v.vehicle_id: [[s.order_id for s in t.stops] for t in v.trips] for v in plan.vehicles}


def _matrix(problem):
    return HaversineProvider().matrix(points_for(problem))


def test_trip_over_capacity_is_named(problem_ab):
    p = replace(problem_ab, orders=[Order("o1", "A", 7_000), Order("o2", "B", 8_000)],
                locks={"o1": ("V1", 1), "o2": ("V1", 1)}, positions={"o1": 1, "o2": 2})
    (msg,) = manual_violations(p)  # sin matriz: basta la capacidad
    assert "viaje 1 de V1" in msg and "15,000 kg" in msg and "10,000 kg" in msg
    assert "Cliente A" in msg and "Cliente B" in msg
    with pytest.raises(ValueError, match="ajuste imposible: el viaje 1 de V1"):
        solve(p, HaversineProvider())


def test_order_too_big_for_the_chosen_truck(problem_ab):
    p = replace(problem_ab, orders=[Order("o1", "A", 12_000)], locks={"o1": ("V1", None)})
    (msg,) = manual_violations(p)
    assert "Cliente A" in msg and "no cabe en V1" in msg


def test_manual_order_that_overruns_the_shift_says_when_it_would_return(problem_ab):
    # 16 t + 16 t en dos viajes de V2: 240 + recarga 120 + 240 min de pura descarga.
    p = replace(problem_ab, orders=[Order("o1", "A", 16_000), Order("o2", "B", 16_000)],
                locks={"o1": ("V2", 1), "o2": ("V2", 2)}, positions={"o1": 1, "o2": 1})
    msgs = manual_violations(p, _matrix(p))
    assert any("viaje 2 de V2 regresaría a las" in m and "17:00" in m for m in msgs)


def test_manual_order_past_client_hours_names_the_client(problem_ab):
    clients = dict(problem_ab.clients)
    clients["B"] = replace(clients["B"], closes_at=11 * 60)
    p = replace(problem_ab, clients=clients, orders=[Order("o1", "A", 8_000), Order("o2", "B", 2_000)],
                locks={"o1": ("V1", 1), "o2": ("V1", 1)}, positions={"o1": 1, "o2": 2})
    (msg,) = manual_violations(p, _matrix(p))
    assert "Cliente B" in msg and "recibe hasta las 11:00" in msg
    ok = replace(p, positions={"o2": 1, "o1": 2})  # al revés sí alcanza
    assert manual_violations(ok, _matrix(ok)) == []


def test_swapping_two_stops_leaves_the_other_trucks_alone(problem_for):
    p = problem_for("normal")
    before, m = solve(p, HaversineProvider())
    routes = _routes(before)
    vid, trips = max(routes.items(), key=lambda kv: len(kv[1][0]))
    assert len(trips[0]) >= 2
    wanted = [list(t) for t in trips]
    wanted[0][0], wanted[0][1] = wanted[0][1], wanted[0][0]
    locks = {oid: (vid, n) for n, trip in enumerate(wanted, start=1) for oid in trip}
    positions = {oid: i for trip in wanted for i, oid in enumerate(trip, start=1)}
    adjusted = replace(p, locks=locks, positions=positions)
    after, m = solve(adjusted, HaversineProvider(), previous=routes)
    assert validate(adjusted, after, m) == []
    new = _routes(after)
    assert new[vid] == wanted
    assert {v: t for v, t in new.items() if v != vid} == {v: t for v, t in routes.items() if v != vid}


def test_recomputing_without_changes_keeps_the_plan(problem_for):
    p = problem_for("promedio")
    plan, _ = solve(p, HaversineProvider())
    again, _ = solve(p, HaversineProvider(), previous=_routes(plan))
    assert _routes(again) == _routes(plan)


def test_a_new_order_is_added_without_dropping_the_rest(problem_for):
    p = problem_for("ligero")
    plan, _ = solve(replace(p, orders=p.orders[:-1]), HaversineProvider())
    full, m = solve(p, HaversineProvider(), previous=_routes(plan))
    assert full.unserved == () and validate(p, full, m) == []


def test_thorough_search_ignores_the_previous_plan(problem_for):
    p = replace(problem_for("ligero"), params=replace(problem_for("ligero").params, time_limit_s=2))
    bad = {"V4": [[o.order_id] for o in p.orders[:3]]}  # un plan anterior cualquiera
    plan, m = solve(p, HaversineProvider(), SearchControl(thorough=True), previous=bad)
    assert plan.unserved == () and validate(p, plan, m) == []


def test_anchored_routes_apply_locks_and_drop_missing_orders(problem_ab):
    previous = {"V1": [["o1", "ya-no-existe"]], "V2": [["o2"]]}
    p = replace(problem_ab, locks={"o2": ("V1", 1), "o1": ("V1", 1)}, positions={"o2": 1, "o1": 2})
    assert anchored_routes(previous, p) == {"V1": [["o2", "o1"]]}
    assert anchored_routes(previous, problem_ab) == {"V1": [["o1"]], "V2": [["o2"]]}
