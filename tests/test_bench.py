"""El banco de medición arma días de prueba repetibles y capturables en la app."""
import json

import pytest

from hcvrp import bench
from hcvrp.domain import SHIFT_START_MIN
from hcvrp.geo.matrix import HaversineProvider
from hcvrp.precheck import points_for, precheck


@pytest.mark.parametrize("case", bench.CASES)
def test_cases_are_repeatable(case):
    assert bench.build(case) == bench.build(case)


@pytest.mark.parametrize("case", bench.CASES)
def test_generated_restrictions_could_be_captured_in_the_app(case):
    p = bench.build(case)
    for o in p.orders:
        client = p.clients[o.client_code]
        opens, closes = client.opens_at - SHIFT_START_MIN, client.closes_at - SHIFT_START_MIN
        # La app rechaza un horario de pedido fuera del horario en que recibe el cliente.
        assert o.window_start is None or opens <= o.window_start < closes
        assert o.window_end is None or opens < o.window_end <= closes
    # Y ningún pedido es imposible por sí solo: lo que quede fuera será por falta de jornada.
    _, impossible = precheck(p, HaversineProvider().matrix(points_for(p)))
    assert impossible == []


def test_restrictions_are_actually_there():
    p = bench.build("promedio + todas las restricciones")
    with_orders = {p.clients[o.client_code].code: p.clients[o.client_code] for o in p.orders}
    assert any((c.opens_at, c.closes_at) != (9 * 60, 18 * 60) for c in with_orders.values())
    assert any(c.blocked_vehicles for c in with_orders.values())
    assert any(c.puesta for c in with_orders.values())
    assert any(o.has_window for o in p.orders)
    out = bench.build("promedio + todas, sin el Volvo")
    assert [v.vehicle_id for v in out.vehicles if not v.available] == ["Volvo"]


def test_average_day_is_delivered_in_full_and_fast():
    result = bench.measure(bench.build("promedio", time_limit_s=20))
    assert result["served_kg"] == result["ordered_kg"] and result["left_orders"] == 0
    assert result["seconds_to_best"] <= result["seconds"] < 15  # no agota el límite
    assert result["stopped_by"] == "sin_mejora"


def test_cli_filters_saves_and_compares(tmp_path, capsys):
    assert bench.main(["--only", "no hay tal caso"]) == 2
    saved = tmp_path / "antes.json"
    assert bench.main(["--only", "camiones que no entran", "--time-limit", "5", "--json", str(saved)]) == 0
    out = capsys.readouterr().out
    assert "kg entregados" in out and "promedio + camiones que no entran" in out
    assert list(json.loads(saved.read_text(encoding="utf-8"))) == ["promedio + camiones que no entran"]
    assert bench.main(["--only", "camiones que no entran", "--time-limit", "5", "--compare", str(saved)]) == 0
    assert "+0 kg entregados" in capsys.readouterr().out
