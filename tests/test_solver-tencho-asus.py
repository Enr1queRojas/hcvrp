from dataclasses import replace

import pytest

from hcvrp.domain import UnservedReason
from hcvrp.geo.matrix import HaversineProvider
from hcvrp.solver import solve
from hcvrp.validate import validate


@pytest.mark.parametrize("name", ["ligero", "normal", "pesado"])
def test_all_served_and_valid(problem_for, name):
    p = problem_for(name); plan, m = solve(p, HaversineProvider())
    assert plan.unserved == () and validate(p, plan, m) == []


def test_pesado_needs_reloads(problem_for):
    plan, _ = solve(problem_for("pesado"), HaversineProvider())
    assert plan.reloads >= 1
    assert all(t.end_min <= 480 for v in plan.vehicles for t in v.trips)


def test_inviable_reasons(problem_for):
    plan, _ = solve(problem_for("inviable"), HaversineProvider())
    reasons = [u.reason for u in plan.unserved]
    assert reasons.count(UnservedReason.EXCEDE_CAPACIDAD) == 1
    assert UnservedReason.SATURACION_FLOTA in reasons


def test_lock_respected(problem_for):
    p = problem_for("ligero"); oid = p.orders[0].order_id
    plan, _ = solve(replace(p, locks={oid: ("V2", 1)}), HaversineProvider())
    trip = next(t for v in plan.vehicles if v.vehicle_id == "V2" for t in v.trips if t.trip_no == 1)
    assert oid in {s.order_id for s in trip.stops}


def test_unavailable_vehicle_unused(problem_for):
    p = problem_for("ligero"); fleet = [replace(v, available=v.vehicle_id != "V4") for v in p.vehicles]
    plan, _ = solve(replace(p, vehicles=fleet), HaversineProvider())
    assert "V4" not in {v.vehicle_id for v in plan.vehicles}


def test_no_orders(problem_for):
    plan, _ = solve(replace(problem_for("ligero"), orders=[]), HaversineProvider())
    assert plan.vehicles == () and plan.cost_mxn == 0


def test_no_vehicles_available(problem_for):
    p = problem_for("ligero"); fleet = [replace(v, available=False) for v in p.vehicles]
    plan, _ = solve(replace(p, vehicles=fleet), HaversineProvider())
    assert plan.vehicles == () and {u.reason for u in plan.unserved} == {UnservedReason.SATURACION_FLOTA}


def test_lock_second_trip(problem_for):
    p = problem_for("pesado")
    base, _ = solve(p, HaversineProvider())
    found = next(
        ((v.vehicle_id, t.stops[0].order_id) for v in base.vehicles for t in v.trips if t.trip_no == 2),
        None,
    )
    if found is None:
        pytest.skip("ningún camión usa el viaje 2 en el escenario pesado")
    vid, oid = found
    plan, m = solve(replace(p, locks={oid: (vid, 2)}), HaversineProvider())
    assert validate(replace(p, locks={oid: (vid, 2)}), plan, m) == []
    trip = next(t for v in plan.vehicles if v.vehicle_id == vid for t in v.trips if t.trip_no == 2)
    assert oid in {s.order_id for s in trip.stops}


def test_lock_on_unservable_order_raises_value_error(problem_ab):
    from hcvrp.domain import Order

    p = replace(
        problem_ab,
        orders=[Order("o1", "A", 50_000), Order("o2", "B", 4000)],
        locks={"o1": ("V2", 1)},
    )
    with pytest.raises(ValueError) as exc:
        solve(p, HaversineProvider())
    msg = str(exc.value)
    assert "o1" in msg and "V2" in msg and "1" in msg and "excede_capacidad" in msg


def test_infeasible_lock_raises_value_error_not_assertion(problem_ab):
    from hcvrp.domain import Order

    # 15 000 kg es planeable (cabe en V2) pero no cabe en V1, al que se bloquea.
    p = replace(
        problem_ab,
        orders=[Order("o1", "A", 15_000), Order("o2", "B", 4000)],
        locks={"o1": ("V1", 1)},
    )
    with pytest.raises(ValueError) as exc:
        solve(p, HaversineProvider())
    msg = str(exc.value)
    assert "o1" in msg and "V1" in msg and "viaje 1" in msg


def test_tiny_far_order_is_served(problem_ab):
    from hcvrp.domain import Client, Location, LocationStatus, Order

    far = Client("F", "Lejano", "Dir F", Location(25.528580 + 0.69, -103.373271), LocationStatus.SINTETICA)
    p = replace(problem_ab, clients={"F": far}, orders=[Order("o1", "F", 1)])
    plan, m = solve(p, HaversineProvider())
    assert plan.unserved == () and validate(p, plan, m) == []


def test_vehicle_only_lock_lets_plan_choose_trip(problem_for):
    p = problem_for("ligero"); oid = p.orders[0].order_id
    locked = replace(p, locks={oid: ("V2", None)})
    plan, m = solve(locked, HaversineProvider())
    assert validate(locked, plan, m) == []
    assert oid in {s.order_id for v in plan.vehicles if v.vehicle_id == "V2" for t in v.trips for s in t.stops}


def test_manual_order_respected(problem_for):
    p = problem_for("pesado")
    base, _ = solve(p, HaversineProvider())
    found = next(
        ((v.vehicle_id, t.trip_no, [s.order_id for s in t.stops])
         for v in base.vehicles for t in v.trips if len(t.stops) >= 3),
        None,
    )
    if found is None:
        pytest.skip("ningún viaje tiene 3 paradas o más")
    vid, trip_no, stops = found
    wanted = list(reversed(stops))  # el orden opuesto al que eligió el motor
    locked = replace(
        p,
        locks={oid: (vid, trip_no) for oid in wanted},
        positions={oid: i for i, oid in enumerate(wanted, start=1)},
    )
    plan, m = solve(locked, HaversineProvider())
    assert validate(locked, plan, m) == []
    trip = next(t for v in plan.vehicles if v.vehicle_id == vid for t in v.trips if t.trip_no == trip_no)
    got = [s.order_id for s in trip.stops if s.order_id in set(wanted)]
    assert got == wanted
    assert sum(u.reason == UnservedReason.SATURACION_FLOTA for u in plan.unserved) == sum(
        u.reason == UnservedReason.SATURACION_FLOTA for u in base.unserved
    )


def test_position_without_trip_lock_rejected(problem_for):
    p = problem_for("ligero"); oid = p.orders[0].order_id
    with pytest.raises(ValueError):
        solve(replace(p, locks={oid: ("V2", None)}, positions={oid: 1}), HaversineProvider())
