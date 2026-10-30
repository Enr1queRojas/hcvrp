from dataclasses import replace

from hcvrp.domain import Stop, Unserved, UnservedReason
from hcvrp.schedule import build_vehicle_plan, summarize
from hcvrp.validate import validate


def _has(violations, text):
    return any(text in v for v in violations)


def _mutate_trip(plan, **trip_changes):
    vp = plan.vehicles[0]
    trip = replace(vp.trips[0], **trip_changes)
    vp = replace(vp, trips=(trip,) + vp.trips[1:])
    return replace(plan, vehicles=(vp,) + plan.vehicles[1:])


def test_valid_plan(problem_ab, plan_ab, tiny_matrix):
    assert validate(problem_ab, plan_ab, tiny_matrix) == []


def test_overload(problem_ab, plan_ab, tiny_matrix):
    trip = plan_ab.vehicles[0].trips[0]
    stops = (trip.stops[0], replace(trip.stops[1], kg=9000))
    v = validate(problem_ab, _mutate_trip(plan_ab, stops=stops), tiny_matrix)
    assert _has(v, "capacidad")
    assert _has(v, "V1")


def test_late_return(problem_ab, plan_ab, tiny_matrix):
    v = validate(problem_ab, _mutate_trip(plan_ab, end_min=481), tiny_matrix)
    assert _has(v, "480")


def test_missing_order(problem_ab, plan_ab, tiny_matrix):
    trip = plan_ab.vehicles[0].trips[0]
    v = validate(problem_ab, _mutate_trip(plan_ab, stops=trip.stops[:1]), tiny_matrix)
    assert _has(v, "o2")


def test_duplicate_order(problem_ab, plan_ab, tiny_matrix):
    trip = plan_ab.vehicles[0].trips[0]
    v = validate(problem_ab, _mutate_trip(plan_ab, stops=trip.stops + (trip.stops[0],)), tiny_matrix)
    assert any("o1" in x and "veces" in x for x in v)


def test_unserved_and_served_duplicate(problem_ab, plan_ab, tiny_matrix):
    plan = replace(plan_ab, unserved=(Unserved("o1", UnservedReason.SATURACION_FLOTA),))
    assert any("o1" in x and "veces" in x for x in validate(problem_ab, plan, tiny_matrix))


def test_short_reload(problem_ab, tiny_matrix):
    o1, o2 = problem_ab.orders
    vp = build_vehicle_plan("V1", [[o1], [o2]], tiny_matrix, problem_ab.params)
    plan = summarize(problem_ab, [vp], [], tiny_matrix)
    assert validate(problem_ab, plan, tiny_matrix) == []
    t1, t2 = vp.trips
    bad_t2 = replace(t2, start_min=t1.end_min + 60)
    bad = replace(plan, vehicles=(replace(vp, trips=(t1, bad_t2)),))
    assert _has(validate(problem_ab, bad, tiny_matrix), "recarga")


def test_altered_cost(problem_ab, plan_ab, tiny_matrix):
    v = validate(problem_ab, replace(plan_ab, cost_mxn=plan_ab.cost_mxn + 1), tiny_matrix)
    assert _has(v, "costo")


def test_lock_violated(problem_ab, plan_ab, tiny_matrix):
    problem_ab.locks = {"o1": ("V2", 1)}
    assert _has(validate(problem_ab, plan_ab, tiny_matrix), "bloqueo")


def test_lock_respected(problem_ab, plan_ab, tiny_matrix):
    problem_ab.locks = {"o1": ("V1", 1)}
    assert validate(problem_ab, plan_ab, tiny_matrix) == []


def test_unavailable_vehicle(problem_ab, plan_ab, tiny_matrix):
    problem_ab.vehicles[0] = replace(problem_ab.vehicles[0], available=False)
    assert _has(validate(problem_ab, plan_ab, tiny_matrix), "V1")


def test_schedule_mismatch(problem_ab, plan_ab, tiny_matrix):
    trip = plan_ab.vehicles[0].trips[0]
    v = validate(problem_ab, _mutate_trip(plan_ab, km=trip.km + 1), tiny_matrix)
    assert _has(v, "km")
    stops = (replace(trip.stops[0], arrival_min=trip.stops[0].arrival_min + 1), trip.stops[1])
    v = validate(problem_ab, _mutate_trip(plan_ab, stops=stops), tiny_matrix)
    assert _has(v, "horario")


def test_first_trip_not_at_zero(problem_ab, plan_ab, tiny_matrix):
    v = validate(problem_ab, _mutate_trip(plan_ab, start_min=5), tiny_matrix)
    assert _has(v, "minuto 0")


def test_too_many_trips(problem_ab, tiny_matrix):
    o1, o2 = problem_ab.orders
    problem_ab.params = replace(problem_ab.params, max_trips_per_vehicle=1)
    vp = build_vehicle_plan("V1", [[o1], [o2]], tiny_matrix, problem_ab.params)
    plan = summarize(problem_ab, [vp], [], tiny_matrix)
    assert _has(validate(problem_ab, plan, tiny_matrix), "exceden el máximo")


def test_stop_kg_mismatch(problem_ab, plan_ab, tiny_matrix):
    trip = plan_ab.vehicles[0].trips[0]
    stops = (replace(trip.stops[0], kg=2500), trip.stops[1])
    v = validate(problem_ab, _mutate_trip(plan_ab, stops=stops), tiny_matrix)
    assert _has(v, "entrega 2500 kg pero el pedido es de 3000")


def test_stop_client_mismatch(problem_ab, plan_ab, tiny_matrix):
    trip = plan_ab.vehicles[0].trips[0]
    stops = (replace(trip.stops[0], client_code="B"), trip.stops[1])
    v = validate(problem_ab, _mutate_trip(plan_ab, stops=stops), tiny_matrix)
    assert _has(v, "corresponde a A")


def test_unknown_order_in_stop_and_unserved(problem_ab, plan_ab, tiny_matrix):
    trip = plan_ab.vehicles[0].trips[0]
    stops = trip.stops + (replace(trip.stops[0], order_id="zz"),)
    v = validate(problem_ab, _mutate_trip(plan_ab, stops=stops), tiny_matrix)
    assert _has(v, "pedido zz no existe")
    plan = replace(plan_ab, unserved=(Unserved("qq", UnservedReason.SATURACION_FLOTA),))
    assert _has(validate(problem_ab, plan, tiny_matrix), "Pedido qq: no servido pero no existe")


def test_unknown_and_duplicate_vehicle(problem_ab, plan_ab, tiny_matrix):
    vp = plan_ab.vehicles[0]
    v = validate(problem_ab, replace(plan_ab, vehicles=(replace(vp, vehicle_id="V9"),)), tiny_matrix)
    assert _has(v, "V9: no existe en la flota")
    v = validate(problem_ab, replace(plan_ab, vehicles=(vp, vp)), tiny_matrix)
    assert _has(v, "V1: aparece más de una vez")


def test_plan_totals_mismatch(problem_ab, plan_ab, tiny_matrix):
    assert _has(validate(problem_ab, replace(plan_ab, reloads=1), tiny_matrix), "recargas")
    assert _has(validate(problem_ab, replace(plan_ab, liters_total=plan_ab.liters_total + 1), tiny_matrix), "litros")
    assert _has(validate(problem_ab, replace(plan_ab, km_total=plan_ab.km_total + 1), tiny_matrix), "km totales")


def test_bad_trip_numbering(problem_ab, plan_ab, tiny_matrix):
    v = validate(problem_ab, _mutate_trip(plan_ab, trip_no=2), tiny_matrix)
    assert _has(v, "numeración de viaje incorrecta")


def test_client_not_in_matrix(problem_ab, plan_ab, tiny_matrix):
    trip = plan_ab.vehicles[0].trips[0]
    stops = (replace(trip.stops[0], client_code="ZZ"), trip.stops[1])
    v = validate(problem_ab, _mutate_trip(plan_ab, stops=stops), tiny_matrix)
    assert _has(v, "sin datos en la matriz")
