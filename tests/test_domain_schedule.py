import pytest

from hcvrp.domain import Order, Params
from hcvrp.schedule import build_trip, build_vehicle_plan, summarize


def test_build_trip_times_and_km(tiny_matrix):
    t = build_trip(1, 0, [Order("o1", "A", 3000), Order("o2", "B", 4000)], tiny_matrix, Params())
    assert [(s.arrival_min, s.departure_min) for s in t.stops] == [(10, 30), (45, 65)]
    assert t.end_min == 85 and t.km == 19 and t.kg == 7000


def test_second_trip_starts_after_reload(tiny_matrix):
    vp = build_vehicle_plan("V1", [[Order("o1", "A", 3000)], [], [Order("o2", "B", 4000)]], tiny_matrix, Params())
    assert [t.trip_no for t in vp.trips] == [1, 2]
    assert vp.trips[1].start_min == vp.trips[0].end_min + 120


def test_summarize_cost_formula(tiny_matrix, problem_ab):
    vp = build_vehicle_plan("V1", [[Order("o1", "A", 3000), Order("o2", "B", 4000)]], tiny_matrix, Params())
    plan = summarize(problem_ab, [vp], [], tiny_matrix)
    assert plan.cost_mxn == pytest.approx(19 * 27 / 4.0 + 7000 * 0.10)  # 828.25
    assert plan.liters_total == pytest.approx(19 / 4.0) and plan.reloads == 0
    assert plan.uses_unverified_locations is True


def test_order_rejects_non_positive_kg():
    with pytest.raises(ValueError):
        Order("o1", "A", 0)


def test_plan_ab_fixture(plan_ab):
    assert len(plan_ab.vehicles) == 1 and plan_ab.km_total == 19


@pytest.mark.parametrize("kw", [{"capacity_kg": 0}, {"capacity_kg": -5}, {"km_per_liter": 0}, {"km_per_liter": -1.0}])
def test_vehicle_rejects_non_positive(kw):
    from hcvrp.domain import Vehicle

    args = {"vehicle_id": "VX", "capacity_kg": 1000, "km_per_liter": 3.0, **kw}
    with pytest.raises(ValueError, match="VX"):
        Vehicle(**args)
