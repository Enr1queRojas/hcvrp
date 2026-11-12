"""Horarios de entrega por pedido."""
from dataclasses import replace

import pytest

from hcvrp.domain import Order
from hcvrp.geo.matrix import HaversineProvider
from hcvrp.precheck import merge_orders
from hcvrp.solver import solve
from hcvrp.validate import validate


def _with_windows(problem, windows):
    """windows: order_id -> (window_start, window_end)."""
    orders = [replace(o, window_start=windows[o.order_id][0], window_end=windows[o.order_id][1])
              if o.order_id in windows else o for o in problem.orders]
    return replace(problem, orders=orders)


def _stops(plan):
    return {s.order_id: s for v in plan.vehicles for t in v.trips for s in t.stops}


def _served_kg(plan):
    return sum(s.kg for s in _stops(plan).values())


def _long_trip(plan, min_stops=3):
    return next(
        (t for v in plan.vehicles for t in v.trips if len(t.stops) >= min_stops), None
    )


def test_order_window_validation():
    with pytest.raises(ValueError):
        Order("o1", "C", 100, window_start=120, window_end=60)
    with pytest.raises(ValueError):
        Order("o1", "C", 100, window_start=-5)
    assert Order("o1", "C", 100, window_end=60).has_window
    assert not Order("o1", "C", 100).has_window


def test_merge_keeps_common_window():
    a = Order("a", "C", 100, window_start=60, window_end=180)
    b = Order("b", "C", 50, window_start=90, window_end=240)
    (m,) = merge_orders([a, b])
    assert (m.kg, m.window_start, m.window_end) == (150, 90, 180)


def test_window_end_pulls_stop_earlier(problem_for):
    p = problem_for("ligero")
    base, m0 = solve(p, HaversineProvider())
    trip = _long_trip(base)
    if trip is None:
        pytest.skip("ningún viaje con 3 paradas")
    last = trip.stops[-1]
    direct = m0.minutes("DEPOT", last.client_code)
    # Entregar a más tardar al llegar directo desde la bodega: obliga a que sea la primera parada.
    wp = _with_windows(p, {last.order_id: (None, direct)})
    plan, m = solve(wp, HaversineProvider())
    assert validate(wp, plan, m) == []
    stop = _stops(plan)[last.order_id]
    assert stop.late_min == 0 and stop.arrival_min == direct
    assert _served_kg(plan) == _served_kg(base)


def test_window_start_is_firm(problem_for):
    p = problem_for("ligero")
    base, _ = solve(p, HaversineProvider())
    first = base.vehicles[0].trips[0].stops[0]
    wp = _with_windows(p, {first.order_id: (240, None)})  # no antes de las 13:00
    plan, m = solve(wp, HaversineProvider())
    assert validate(wp, plan, m) == []
    stop = _stops(plan)[first.order_id]
    assert stop.arrival_min >= 240
    assert _served_kg(plan) == _served_kg(base)


def test_wait_is_reported(problem_for):
    p = problem_for("ligero")
    oid = p.orders[0].order_id
    # Un solo pedido con horario tardío: el camión llega antes y espera.
    wp = replace(_with_windows(p, {oid: (300, 360)}), orders=[_with_windows(p, {oid: (300, 360)}).orders[0]])
    plan, m = solve(wp, HaversineProvider())
    assert validate(wp, plan, m) == []
    (stop,) = _stops(plan).values()
    assert stop.arrival_min == 300 and stop.wait_min > 0
    assert stop.departure_min == 300 + wp.params.service_time(stop.kg)


def test_impossible_window_delivers_late_instead_of_dropping(problem_for):
    p = problem_for("ligero")
    base, _ = solve(p, HaversineProvider())
    oid = p.orders[0].order_id
    wp = _with_windows(p, {oid: (None, 1)})  # imposible: a las 09:01
    plan, m = solve(wp, HaversineProvider())
    assert validate(wp, plan, m) == []
    stop = _stops(plan)[oid]
    assert stop.late_min > 0
    assert _served_kg(plan) == _served_kg(base)


def _narrow_windows(problem):
    """Un tercio de los pedidos con horarios estrechos y encontrados."""
    return {
        o.order_id: ((i % 4) * 90, (i % 4) * 90 + 60)
        for i, o in enumerate(problem.orders) if i % 3 == 0
    }


def test_many_windows_never_cost_kilos(problem_for):
    p = problem_for("ligero")  # con holgura en la jornada, los horarios se acomodan sin dejar kilos
    base, _ = solve(p, HaversineProvider())
    wp = _with_windows(p, _narrow_windows(p))
    plan, m = solve(wp, HaversineProvider())
    assert validate(wp, plan, m) == []
    assert _served_kg(plan) == _served_kg(base) == sum(o.kg for o in p.orders)


def test_windows_on_a_saturated_day_stay_valid(problem_for):
    p = problem_for("pesado")
    wp = _with_windows(p, _narrow_windows(p))
    plan, m = solve(wp, HaversineProvider())
    assert validate(wp, plan, m) == []
    # Un "no antes de" nunca se rompe, ni cuando la jornada no alcanza para todo.
    for stop in _stops(plan).values():
        assert stop.window_start is None or stop.arrival_min >= stop.window_start


def test_window_start_after_shift_is_unservable(problem_for):
    p = problem_for("ligero")
    oid = p.orders[0].order_id
    wp = _with_windows(p, {oid: (p.params.shift_minutes, None)})
    plan, _ = solve(wp, HaversineProvider())
    assert oid in {u.order_id for u in plan.unserved}


# --- Horario de recepción del cliente ---------------------------------------------------------

from hcvrp.baseline import baseline_plan  # noqa: E402
from hcvrp.domain import UnservedReason  # noqa: E402


def _with_client_hours(problem, code, opens_at, closes_at):
    clients = dict(problem.clients)
    clients[code] = replace(clients[code], opens_at=opens_at, closes_at=closes_at)
    return replace(problem, clients=clients)


def test_default_client_hours_change_nothing(problem_for):
    p = problem_for("normal")
    c = next(iter(p.clients.values()))
    assert (c.opens_at, c.closes_at) == (9 * 60, 18 * 60)


def test_client_opening_is_firm(problem_for):
    p = problem_for("ligero")
    code = p.orders[0].client_code
    cp = _with_client_hours(p, code, 13 * 60, 18 * 60)  # abre a las 13:00
    plan, m = solve(cp, HaversineProvider())
    assert validate(cp, plan, m) == []
    stop = _stops(plan)[p.orders[0].order_id]
    assert stop.arrival_min >= 240


def test_client_closing_is_firm(problem_for):
    p = problem_for("ligero")
    o = p.orders[0]
    _, m0 = solve(replace(p, orders=[o]), HaversineProvider())
    # Cierra 20 min después de lo mínimo para llegar directo y descargar todo.
    closes = m0.minutes("DEPOT", o.client_code) + p.params.service_time(o.kg) + 20
    cp = _with_client_hours(p, o.client_code, 9 * 60, 9 * 60 + closes)
    plan, m = solve(cp, HaversineProvider())
    assert validate(cp, plan, m) == []
    stop = _stops(plan).get(o.order_id)
    assert stop is not None and stop.departure_min <= closes  # termina de descargar antes de cerrar


def test_unloading_longer_than_client_hours_goes_to_another_day(problem_for):
    p = problem_for("ligero")
    o = p.orders[0]
    assert p.params.service_time(o.kg) > 90
    cp = _with_client_hours(p, o.client_code, 9 * 60, 10 * 60 + 30)  # cierra a las 10:30
    plan, m = solve(cp, HaversineProvider())
    assert validate(cp, plan, m) == []
    assert {u.order_id: u.reason for u in plan.unserved}[o.order_id] == UnservedReason.FUERA_HORARIO_CLIENTE


def test_unreachable_before_closing_goes_to_another_day(problem_for):
    p = problem_for("ligero")
    o = p.orders[0]
    cp = _with_client_hours(p, o.client_code, 0, 9 * 60 + 5)  # cierra a las 09:05
    plan, _ = solve(cp, HaversineProvider())
    reasons = {u.order_id: u.reason for u in plan.unserved}
    assert reasons[o.order_id] == UnservedReason.FUERA_HORARIO_CLIENTE


def test_order_window_outside_client_hours_is_clipped(problem_for):
    p = problem_for("ligero")
    o = p.orders[0]
    cp = _with_client_hours(
        _with_windows(p, {o.order_id: (0, None)}), o.client_code, 12 * 60, 18 * 60
    )
    plan, m = solve(cp, HaversineProvider())
    assert validate(cp, plan, m) == []
    assert _stops(plan)[o.order_id].arrival_min >= 180  # el cliente abre a las 12:00


def test_baseline_counts_waits(problem_for):
    """La línea base debe sumar las esperas: antes armaba viajes que se pasaban de la jornada."""
    p = problem_for("pesado")
    windows = {o.order_id: (300, None) for o in p.orders[::2]}  # muchos "desde las 14:00"
    wp = _with_windows(p, windows)
    plan, m = baseline_plan(wp, HaversineProvider())  # lanza AssertionError si es inválida
    assert validate(replace(wp, locks={}, positions={}), plan, m) == []
