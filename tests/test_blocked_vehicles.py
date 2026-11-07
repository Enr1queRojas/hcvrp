"""Camiones que no pueden entrar con ciertos clientes (por dimensiones)."""
from dataclasses import replace

import pytest

from hcvrp.baseline import baseline_plan
from hcvrp.domain import Client, LocationStatus, UnservedReason
from hcvrp.geo.matrix import HaversineProvider
from hcvrp.solver import solve
from hcvrp.validate import validate


def _block(problem, code, vehicles):
    clients = dict(problem.clients)
    clients[code] = replace(clients[code], blocked_vehicles=tuple(vehicles))
    return replace(problem, clients=clients)


def _truck_of(plan):
    return {s.order_id: v.vehicle_id for v in plan.vehicles for t in v.trips for s in t.stops}


def test_blocked_list_is_normalized():
    c = Client("X", "X", "", None, LocationStatus.PENDIENTE, blocked_vehicles=("V3", "V1", "V3"))
    assert c.blocked_vehicles == ("V1", "V3")
    assert not c.can_receive("V1") and c.can_receive("V2")


def test_blocked_truck_never_serves_client(problem_for):
    p = problem_for("normal")
    base, _ = solve(p, HaversineProvider())
    by_order = _truck_of(base)
    # Bloquear para cada cliente justo el camión que hoy lo atiende.
    bp = p
    for o in p.orders:
        if o.order_id in by_order:
            bp = _block(bp, o.client_code, [by_order[o.order_id]])
    plan, m = solve(bp, HaversineProvider())
    assert validate(bp, plan, m) == []
    for oid, vid in _truck_of(plan).items():
        assert vid != by_order[oid]


def test_no_truck_fits_goes_to_another_day(problem_for):
    p = problem_for("ligero")
    o = p.orders[0]
    bp = _block(p, o.client_code, [v.vehicle_id for v in p.vehicles])
    plan, _ = solve(bp, HaversineProvider())
    assert {u.order_id: u.reason for u in plan.unserved}[o.order_id] == UnservedReason.NINGUN_CAMION_ENTRA


def test_capacity_check_only_counts_trucks_that_fit(problem_for):
    p = problem_for("ligero")
    o = p.orders[0]
    biggest = max(v.capacity_kg for v in p.vehicles)
    small = [v.vehicle_id for v in p.vehicles if v.capacity_kg == biggest]
    bp = _block(replace(p, orders=[replace(o, kg=biggest)] + p.orders[1:]), o.client_code, small)
    plan, _ = solve(bp, HaversineProvider())
    assert {u.order_id: u.reason for u in plan.unserved}[o.order_id] == UnservedReason.EXCEDE_CAPACIDAD


def test_lock_on_blocked_truck_is_rejected(problem_for):
    p = problem_for("ligero")
    o = p.orders[0]
    bp = replace(_block(p, o.client_code, ["V2"]), locks={o.order_id: ("V2", None)})
    with pytest.raises(ValueError, match="no puede entrar"):
        solve(bp, HaversineProvider())


def test_lock_and_block_combine(problem_for):
    p = problem_for("ligero")
    o = p.orders[0]
    bp = replace(_block(p, o.client_code, ["V2"]), locks={o.order_id: ("V1", None)})
    plan, m = solve(bp, HaversineProvider())
    assert validate(bp, plan, m) == []
    assert _truck_of(plan)[o.order_id] == "V1"


def test_baseline_respects_blocked_trucks(problem_for):
    p = problem_for("normal")
    blocked = {o.client_code: [p.vehicles[0].vehicle_id] for o in p.orders[::2]}
    bp = p
    for code, vs in blocked.items():
        bp = _block(bp, code, vs)
    plan, m = baseline_plan(bp, HaversineProvider())  # lanza AssertionError si es inválida
    for v in plan.vehicles:
        for t in v.trips:
            for s in t.stops:
                assert v.vehicle_id not in blocked.get(s.client_code, [])
