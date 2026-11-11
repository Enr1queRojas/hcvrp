"""Recálculo en segundo plano: qué va primero, qué se corta y qué no se repite."""
import time
from datetime import date, timedelta

from hcvrp.api import planning
from hcvrp.api.db import connect
from hcvrp.api.planning import FreePlans, Recalculator, build_problem, inputs_hash, run_planning
from hcvrp.api.store import (
    add_order, get_plan_row, list_clients, list_orders, replace_orders, set_lock, set_params,
)
from hcvrp.domain import Params
from hcvrp.geo.matrix import HaversineProvider
from hcvrp.scenarios import generate_scenario
from hcvrp.solver import SearchCancelled

D = date(2026, 10, 31)


def _load(conn, day, name="ligero"):
    replace_orders(conn, day, [(o.client_code, o.kg) for o in generate_scenario(name, list_clients(conn))])


def test_free_plan_is_not_recomputed_on_every_manual_change(settings, monkeypatch):
    conn = connect(settings.db_path)
    _load(conn, D)
    solved = []  # True: con pedidos fijados; False: el plan sin fijar
    real = planning.solve

    def counting(problem, provider, control=None):
        solved.append(bool(problem.locks))
        return real(problem, provider, control)

    monkeypatch.setattr(planning, "solve", counting)
    free_plans = FreePlans()
    run_planning(build_problem(conn, D), HaversineProvider(), free_plans=free_plans)
    assert solved == [False]

    first, second = [int(o.order_id) for o in list_orders(conn, D)[:2]]
    set_lock(conn, first, "V2")
    out = run_planning(build_problem(conn, D), HaversineProvider(), free_plans=free_plans)
    assert solved == [False, True]  # el plan sin fijar ya se conocía
    assert out["lock_cost_diff_mxn"] is not None and out["lock_cost_diff_mxn"] >= 0
    set_lock(conn, second, "V3")
    run_planning(build_problem(conn, D), HaversineProvider(), free_plans=free_plans)
    assert solved == [False, True, True]

    # Sin memoria (recién arrancado el servicio) se calcula una vez y se recuerda.
    fresh = FreePlans()
    run_planning(build_problem(conn, D), HaversineProvider(), free_plans=fresh)
    run_planning(build_problem(conn, D), HaversineProvider(), free_plans=fresh)
    assert solved[3:] == [True, False, True]


def test_free_plans_forget_the_oldest():
    from hcvrp.domain import DEPOT, Client, LocationStatus, Order, Problem

    plans = FreePlans(size=2)
    clients = {"C": Client("C", "C", "", None, LocationStatus.PENDIENTE)}
    problems = [Problem(DEPOT, clients, [], [Order("o", "C", kg)], Params()) for kg in (1, 2, 3)]
    for i, p in enumerate(problems):
        plans.put(p, float(i), i)
    assert plans.get(problems[0]) is None and plans.get(problems[2]) == (2.0, 2)


def test_compute_is_cut_short_when_its_data_changes(settings, monkeypatch):
    conn = connect(settings.db_path)
    set_params(conn, Params(time_limit_s=20))
    _load(conn, D)
    # Sin corte por estancamiento, el primer cálculo duraría los 20 s completos.
    monkeypatch.setattr("hcvrp.solver.STALL_S", 60.0)
    outcomes = []
    real = planning.run_planning

    def spy(problem, provider, geometry=None, **kwargs):
        try:
            result = real(problem, provider, geometry, **kwargs)
        except SearchCancelled:
            outcomes.append("cortado")
            monkeypatch.setattr("hcvrp.solver.STALL_S", 0.2)  # el siguiente ya puede acabar pronto
            raise
        outcomes.append("listo")
        return result

    monkeypatch.setattr("hcvrp.api.planning.run_planning", spy)
    recalc = Recalculator(settings, HaversineProvider())
    started = time.monotonic()
    recalc.request(D)
    time.sleep(1.0)  # ya está calculando
    add_order(conn, D, "AARON", 500)  # cambian los datos de ese día
    recalc.request(D)
    assert recalc.wait_idle(30)
    recalc.stop()
    assert outcomes == ["cortado", "listo"]
    assert time.monotonic() - started < 15
    row = get_plan_row(conn, D)
    assert row["status"] == "listo" and row["inputs_hash"] == inputs_hash(build_problem(conn, D))


def test_request_without_changes_does_not_cut_the_running_compute(settings, monkeypatch):
    conn = connect(settings.db_path)
    set_params(conn, Params(time_limit_s=3))
    _load(conn, D)
    monkeypatch.setattr("hcvrp.solver.STALL_S", 60.0)  # el cálculo dura sus 3 s
    recalc = Recalculator(settings, HaversineProvider())
    recalc.request(D)
    time.sleep(0.8)
    recalc.request(D)  # p. ej. se editó un cliente que no tiene pedido ese día
    assert recalc.wait_idle(30)
    recalc.stop()
    row = get_plan_row(conn, D)
    assert row["status"] == "listo" and row["result"]["summary"]["served_kg"] > 0


def _order_of_compute(settings, monkeypatch, viewed):
    today = date.today()
    days = {"pasado": today - timedelta(days=3), "mañana": today + timedelta(days=1), "después": today + timedelta(days=9)}
    conn = connect(settings.db_path)
    for day in days.values():
        add_order(conn, day, "AARON", 1000)
    count = iter(range(100))
    monkeypatch.setattr(
        "hcvrp.api.planning.run_planning", lambda problem, provider, geometry=None, **kwargs: {"turno": next(count)}
    )
    recalc = Recalculator(settings, HaversineProvider())
    recalc.pause()
    if viewed:
        recalc.touch(days[viewed])
    recalc.request(None)  # p. ej. cambió un parámetro: todas las fechas
    recalc.resume()
    assert recalc.wait_idle(30)
    recalc.stop()
    turn = {name: get_plan_row(conn, day)["result"]["turno"] for name, day in days.items()}
    return sorted(turn, key=turn.get)


def test_upcoming_days_are_computed_before_past_ones(settings, monkeypatch):
    assert _order_of_compute(settings, monkeypatch, viewed=None) == ["mañana", "después", "pasado"]


def test_the_date_on_screen_is_computed_first(settings, monkeypatch):
    assert _order_of_compute(settings, monkeypatch, viewed="pasado") == ["pasado", "mañana", "después"]


def test_looking_at_a_plan_marks_its_date_as_on_screen(client, monkeypatch):
    seen = []
    monkeypatch.setattr(client.app.state.recalc, "touch", seen.append)
    client.get("/api/plan?date=2026-10-31")
    assert seen == [D]


def test_recalcular_searches_thoroughly(client, monkeypatch):
    modes = []
    real = planning.run_planning

    def spy(problem, provider, geometry=None, **kwargs):
        modes.append(kwargs["control"].thorough)
        return real(problem, provider, geometry, **kwargs)

    monkeypatch.setattr("hcvrp.api.planning.run_planning", spy)
    recalc = client.app.state.recalc
    client.post("/api/orders", json={"date": "2026-10-31", "client_code": "AARON", "kg": 500})
    assert recalc.wait_idle(60)
    assert client.post("/api/plan/recalcular?date=2026-10-31").status_code == 202
    assert recalc.wait_idle(60)
    assert modes == [False, True]
