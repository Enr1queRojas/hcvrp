from dataclasses import replace
from datetime import date

import pytest

from hcvrp.api import planning
from hcvrp.api.db import connect
from hcvrp.api.planning import PlanningError, build_problem, inputs_hash, run_planning
from hcvrp.api.store import (
    add_order, get_fleet, list_clients, replace_orders, set_fleet, set_lock,
)
from hcvrp.geo.matrix import HaversineProvider
from hcvrp.scenarios import generate_scenario

D = date(2026, 10, 31)


@pytest.fixture
def conn(settings):
    return connect(settings.db_path)


def scenario_pairs(conn, name):
    return [(o.client_code, o.kg) for o in generate_scenario(name, list_clients(conn))]


def test_plan_ligero_valid_and_complete(conn):
    replace_orders(conn, D, scenario_pairs(conn, "ligero"))
    problem = build_problem(conn, D)
    out = run_planning(problem, HaversineProvider())
    assert out["shift_start"] == "09:00"
    assert out["summary"]["unserved_kg"] == 0
    assert out["summary"]["served_kg"] == sum(o.kg for o in problem.orders)
    assert out["afternoon_load"]
    assert all(v["trips"][0]["trip_no"] == 1 for v in out["vehicles"])
    assert out["uses_unverified_locations"] is True and out["unverified_clients"]
    assert out["lock_cost_diff_mxn"] is None
    assert out["comparison"]["optimized_is_better_or_equal"] is True
    assert out["baseline"]["served_kg"] > 0


def test_trip_details(conn):
    replace_orders(conn, D, [("AARON", 5000)])
    out = run_planning(build_problem(conn, D), HaversineProvider())
    vehicle = out["vehicles"][0]
    trip = vehicle["trips"][0]
    assert trip["kg"] == 5000
    assert trip["capacity_pct"] == round(100 * 5000 / vehicle["capacity_kg"], 1)
    assert trip["geometry"] == []
    stop = trip["stops"][0]
    assert stop["client_code"] == "AARON" and stop["client_name"] == "Cliente AARON"
    assert stop["kg"] == 5000 and stop["arrival_min"] < stop["departure_min"]
    assert out["afternoon_load"] == [{
        "vehicle_id": vehicle["vehicle_id"], "kg": 5000, "orders": 1, "capacity_pct": trip["capacity_pct"],
    }]


def test_inviable_reports_reason_labels(conn):
    replace_orders(conn, D, scenario_pairs(conn, "inviable"))
    out = run_planning(build_problem(conn, D), HaversineProvider())
    assert "excede_capacidad" in {u["reason"] for u in out["unserved"]}
    assert all(u["reason_label"] and u["client_name"] for u in out["unserved"])
    assert out["summary"]["unserved_kg"] == sum(u["kg"] for u in out["unserved"])


def test_lock_is_honored_and_cost_diff_reported(conn):
    orders = replace_orders(conn, D, scenario_pairs(conn, "ligero"))
    set_lock(conn, int(orders[0].order_id), "V1", 2)
    out = run_planning(build_problem(conn, D), HaversineProvider())
    v1 = next(v for v in out["vehicles"] if v["vehicle_id"] == "V1")
    trip2 = next(t for t in v1["trips"] if t["trip_no"] == 2)
    assert orders[0].order_id in [s["order_id"] for s in trip2["stops"]]
    assert out["lock_cost_diff_mxn"] is not None and out["lock_cost_diff_mxn"] >= -0.01


def test_lock_diff_not_negative_when_same_kg(conn, monkeypatch):
    # Con tiempo limitado, el "óptimo" sin bloqueos puede salir más caro que el plan bloqueado.
    real_solve = planning.solve

    def solve(problem, provider):
        plan, matrix = real_solve(problem, provider)
        return (plan if problem.locks else replace(plan, cost_mxn=plan.cost_mxn + 1000)), matrix

    monkeypatch.setattr(planning, "solve", solve)
    orders = replace_orders(conn, D, [("AARON", 1000), ("BETO", 1000)])
    set_lock(conn, int(orders[0].order_id), "V1", 1)
    out = run_planning(build_problem(conn, D), HaversineProvider())
    assert out["lock_cost_diff_mxn"] == 0.0


def test_impossible_lock_raises_planning_error_in_spanish(conn):
    orders = replace_orders(conn, D, scenario_pairs(conn, "ligero"))
    set_fleet(conn, [replace(v, available=(v.vehicle_id != "V1")) for v in get_fleet(conn)])
    set_lock(conn, int(orders[0].order_id), "V1", 1)
    with pytest.raises(PlanningError, match="el camión V1 no está disponible"):
        run_planning(build_problem(conn, D), HaversineProvider())


def test_lock_on_removed_truck_message_in_spanish(conn):
    orders = replace_orders(conn, D, [("AARON", 1000)])
    set_lock(conn, int(orders[0].order_id), "V1", 1)
    set_fleet(conn, [v for v in get_fleet(conn) if v.vehicle_id != "V1"])
    with pytest.raises(PlanningError, match="el camión V1 ya no existe"):
        run_planning(build_problem(conn, D), HaversineProvider())


def test_inputs_hash_changes_with_data(conn):
    replace_orders(conn, D, [("AARON", 1000)])
    h1 = inputs_hash(build_problem(conn, D))
    assert h1 == inputs_hash(build_problem(conn, D))
    add_order(conn, D, "AARON", 1)
    assert inputs_hash(build_problem(conn, D)) != h1


def test_inputs_hash_ignores_clients_without_orders(conn):
    replace_orders(conn, D, [("AARON", 1000)])
    problem = build_problem(conn, D)
    other = dict(problem.clients)
    del other["BETO"]
    assert inputs_hash(replace(problem, clients=other)) == inputs_hash(problem)


def test_plan_out_reports_puesta(conn):
    """Un pedido más grande que cualquier camión, con puesta: se entrega una parte y el resto pasa a otro día."""
    from dataclasses import replace as _replace

    from hcvrp.api.planning import build_problem, run_planning
    from hcvrp.api.store import add_order, get_client, upsert_client
    from hcvrp.geo.matrix import HaversineProvider

    code = next(iter(list_clients(conn)))
    upsert_client(conn, _replace(get_client(conn, code), puesta=True))
    add_order(conn, D, code, 40_000)
    out = run_planning(build_problem(conn, D), HaversineProvider())
    stop = next(s for v in out["vehicles"] for t in v["trips"] for s in t["stops"])
    assert (stop["kg"], stop["ordered_kg"]) == (6_000, 40_000)
    (u,) = out["unserved"]
    assert (u["kg"], u["reason"]) == (34_000, "puesta_parcial")
    assert out["summary"]["puesta_stops"] == 1 and out["summary"]["unserved_kg"] == 34_000
