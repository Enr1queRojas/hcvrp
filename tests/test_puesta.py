"""Puesta: en urgencia, un cliente con puesta recibe solo 10-15% de su pedido y el resto pasa a otro día."""
from dataclasses import replace

from hcvrp.domain import UnservedReason, puesta_amounts
from hcvrp.geo.matrix import HaversineProvider
from hcvrp.solver import solve
from hcvrp.validate import validate


def _puesta(problem, codes=None):
    clients = {
        code: replace(c, puesta=True) if codes is None or code in codes else c
        for code, c in problem.clients.items()
    }
    return replace(problem, clients=clients)


def _delivered(plan):
    return {s.order_id: s.kg for v in plan.vehicles for t in v.trips for s in t.stops}


def _served_kg(plan):
    return sum(_delivered(plan).values())


def _fully_dropped(plan):
    return {u.order_id for u in plan.unserved if u.kg is None}


def test_puesta_amounts():
    assert puesta_amounts(10_000) == (1_500, 1_000)
    assert puesta_amounts(5) == (1,)  # 15% y 10% redondean igual
    assert puesta_amounts(1) == ()


def test_no_puesta_when_everything_fits(problem_for):
    p = _puesta(problem_for("ligero"))
    plan, m = solve(p, HaversineProvider())
    assert validate(p, plan, m) == []
    assert all(u.reason != UnservedReason.PUESTA_PARCIAL for u in plan.unserved)
    assert _delivered(plan) == {o.order_id: o.kg for o in p.orders}


def test_oversized_order_gets_puesta_instead_of_next_day(problem_for):
    p = problem_for("ligero")
    big = replace(p.orders[0], kg=40_000)  # más que cualquier camión de la flota de pruebas (30 t)
    p = replace(p, orders=[big] + p.orders[1:])
    without, _ = solve(p, HaversineProvider())
    assert big.order_id in _fully_dropped(without)

    pp = _puesta(p, {big.client_code})
    plan, m = solve(pp, HaversineProvider())
    assert validate(pp, plan, m) == []
    assert _delivered(plan)[big.order_id] == 6_000  # 15% de 40,000
    rest = next(u for u in plan.unserved if u.order_id == big.order_id)
    assert (rest.reason, rest.kg) == (UnservedReason.PUESTA_PARCIAL, 34_000)


def test_puesta_when_fleet_is_saturated(problem_for):
    p = problem_for("inviable")  # más kilos de los que caben
    without, _ = solve(p, HaversineProvider())
    pp = _puesta(p)
    plan, m = solve(pp, HaversineProvider())
    assert validate(pp, plan, m) == []
    assert _served_kg(plan) >= _served_kg(without)
    assert len(_fully_dropped(plan)) < len(_fully_dropped(without))
    partial = [u for u in plan.unserved if u.reason == UnservedReason.PUESTA_PARCIAL]
    assert partial
    for u in partial:
        ordered = next(o.kg for o in pp.orders if o.order_id == u.order_id)
        assert _delivered(plan)[u.order_id] in puesta_amounts(ordered)
        assert _delivered(plan)[u.order_id] + u.kg == ordered


def test_locked_order_is_delivered_complete(problem_for):
    p = problem_for("ligero")
    o = p.orders[0]
    pp = replace(_puesta(p, {o.client_code}), locks={o.order_id: ("V1", None)})
    plan, m = solve(pp, HaversineProvider())
    assert validate(pp, plan, m) == []
    assert _delivered(plan)[o.order_id] == o.kg


def test_validator_rejects_partial_without_puesta(problem_for):
    p = problem_for("ligero")
    big = replace(p.orders[0], kg=40_000)
    p = replace(p, orders=[big] + p.orders[1:])
    pp = _puesta(p, {big.client_code})
    plan, m = solve(pp, HaversineProvider())
    # El mismo plan contra el problema sin puesta: entregar una parte ya no es válido.
    assert any("entrega 6000 kg" in v for v in validate(p, plan, m))
