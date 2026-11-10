import dataclasses

import pytest

from hcvrp.domain import (
    DEPOT, Client, Location, LocationStatus, Order, Params, Problem,
    UnservedReason,
)
from hcvrp.geo.matrix import Matrix
from hcvrp.precheck import merge_orders, points_for, precheck

from fleets import TEST_FLEET


def test_merge_same_client():
    assert merge_orders([Order("a", "X", 3000), Order("b", "X", 2000)]) == [Order("a", "X", 5000)]

LOC = Location(25.53, -103.37)


def _client(code, loc=LOC):
    return Client(code, f"Cliente {code}", f"Dir {code}", loc, LocationStatus.SINTETICA)


def _matrix(minutes=30):
    rows = [[0, minutes], [minutes, 0]]
    return Matrix(["DEPOT", "C"], [[0.0, 10.0], [10.0, 0.0]], rows)


def _problem(kg=3000, loc=LOC, fleet=None, locks=None, orders=None, clients=None, params=None):
    return Problem(
        DEPOT,
        clients if clients is not None else {"C": _client("C", loc)},
        list(fleet if fleet is not None else TEST_FLEET),
        orders if orders is not None else [Order("o1", "C", kg)],
        params or Params(),
        locks or {},
    )


def _reasons(problem, matrix):
    planeable, unserved = precheck(problem, matrix)
    return planeable, {u.order_id: u.reason for u in unserved}


def test_ok_order_is_plannable():
    planeable, reasons = _reasons(_problem(), _matrix())
    assert planeable == [Order("o1", "C", 3000)] and reasons == {}


def test_unknown_client_raises():
    with pytest.raises(ValueError, match="NOEXISTE"):
        precheck(_problem(orders=[Order("o1", "NOEXISTE", 100)]), _matrix())


def test_no_coordinates():
    _, reasons = _reasons(_problem(loc=None), _matrix())
    assert reasons == {"o1": UnservedReason.SIN_COORDENADAS}


def test_exceeds_capacity():
    planeable, reasons = _reasons(_problem(kg=35_000), _matrix())
    assert planeable == [] and reasons == {"o1": UnservedReason.EXCEDE_CAPACIDAD}


def test_exceeds_available_capacity_when_v4_unavailable():
    fleet = [dataclasses.replace(v, available=False) if v.vehicle_id == "V4" else v
             for v in TEST_FLEET]
    _, reasons = _reasons(_problem(kg=25_000, fleet=fleet), _matrix())
    assert reasons == {"o1": UnservedReason.EXCEDE_CAPACIDAD}


def test_does_not_fit_shift():
    _, reasons = _reasons(_problem(), _matrix(minutes=240))
    assert reasons == {"o1": UnservedReason.NO_CABE_JORNADA}


def _unavail_fleet():
    return [dataclasses.replace(v, available=False) if v.vehicle_id == "V4" else v
            for v in TEST_FLEET]


def test_lock_to_unavailable_vehicle_raises():
    with pytest.raises(ValueError, match="unavailable"):
        precheck(_problem(fleet=_unavail_fleet(), locks={"o1": ("V4", 1)}), _matrix())


def test_lock_to_unknown_vehicle_raises():
    with pytest.raises(ValueError, match="unknown vehicle"):
        precheck(_problem(locks={"o1": ("V9", 1)}), _matrix())


@pytest.mark.parametrize("trip_no", [4, 0])
def test_lock_bad_trip_no_raises(trip_no):
    with pytest.raises(ValueError, match="trip_no"):
        precheck(_problem(locks={"o1": ("V1", trip_no)}), _matrix())


def test_lock_unknown_order_raises():
    with pytest.raises(ValueError, match="zzz"):
        precheck(_problem(locks={"zzz": ("V1", 1)}), _matrix())


def test_lock_on_merged_away_order_names_survivor():
    orders = [Order("o1", "C", 1000), Order("o2", "C", 2000)]
    with pytest.raises(ValueError, match="o1"):
        precheck(_problem(orders=orders, locks={"o2": ("V1", 1)}), _matrix())


def test_valid_lock_passes():
    planeable, _ = _reasons(_problem(locks={"o1": ("V1", 2)}), _matrix())
    assert [o.order_id for o in planeable] == ["o1"]


def test_precheck_merges_orders():
    orders = [Order("o1", "C", 1000), Order("o2", "C", 2000)]
    planeable, _ = _reasons(_problem(orders=orders), _matrix())
    assert planeable == [Order("o1", "C", 3000)]


def test_points_for():
    clients = {"C": _client("C"), "N": _client("N", None), "U": _client("U")}
    p = _problem(clients=clients, orders=[Order("o1", "C", 10), Order("o2", "N", 10)])
    pts = points_for(p)
    assert list(pts) == ["DEPOT", "C"] and pts["DEPOT"] == DEPOT and pts["C"] == LOC


def test_no_available_vehicles_skips_capacity_check():
    fleet = [dataclasses.replace(v, available=False) for v in TEST_FLEET]
    # Sin descarga por tonelada, para aislar la capacidad: 35 t no se descargan en una jornada.
    flat = Params(service_minutes=20, unload_minutes_per_ton=0)
    planeable, reasons = _reasons(_problem(kg=35_000, fleet=fleet, params=flat), _matrix())
    assert planeable == [Order("o1", "C", 35_000)] and reasons == {}


# --- Descarga por tonelada ---------------------------------------------------------------------

def test_unloading_that_does_not_fit_the_shift():
    # 30 t caben en V4, pero descargarlas toma 450 min: con 30 de ida y 30 de vuelta son 510.
    _, reasons = _reasons(_problem(kg=30_000), _matrix())
    assert reasons == {"o1": UnservedReason.NO_CABE_JORNADA}
    planeable, reasons = _reasons(_problem(kg=28_000), _matrix())  # 420 + 60 = 480: justo
    assert [o.kg for o in planeable] == [28_000] and reasons == {}


def test_unloading_must_end_before_the_client_closes():
    closes_noon = {"C": dataclasses.replace(_client("C"), closes_at=12 * 60)}
    # Llega 09:30; 10 t tardan 150 min y terminan a las 12:00 en punto.
    planeable, _ = _reasons(_problem(kg=10_000, clients=closes_noon), _matrix())
    assert [o.kg for o in planeable] == [10_000]
    _, reasons = _reasons(_problem(kg=10_100, clients=closes_noon), _matrix())
    assert reasons == {"o1": UnservedReason.FUERA_HORARIO_CLIENTE}


def test_puesta_keeps_an_order_plannable_when_only_part_can_be_unloaded():
    client = dataclasses.replace(_client("C"), closes_at=12 * 60, puesta=True)
    planeable, reasons = _reasons(_problem(kg=20_000, clients={"C": client}), _matrix())
    assert [o.kg for o in planeable] == [20_000] and reasons == {}  # su puesta (3 t, 45 min) sí cabe
    locked = _problem(kg=20_000, clients={"C": client}, locks={"o1": ("V2", 1)})
    with pytest.raises(ValueError, match="fuera_horario_cliente"):  # fijado va completo: no cabe
        precheck(locked, _matrix())
