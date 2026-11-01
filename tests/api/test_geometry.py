from datetime import date

import httpx
import pytest

from hcvrp.api import seed
from hcvrp.api.db import connect
from hcvrp.api.planning import build_problem, make_geometry, run_planning
from hcvrp.api.settings import Settings
from hcvrp.api.store import get_client, list_clients, replace_orders, upsert_client
from hcvrp.domain import DEPOT, Client, Location, LocationStatus
from hcvrp.geo.directions import OrsDirections, straight_line
from hcvrp.geo.matrix import HaversineProvider
from hcvrp.scenarios import generate_scenario

D = date(2026, 10, 31)


@pytest.fixture
def conn(settings):
    return connect(settings.db_path)


def scenario_pairs(conn, name):
    return [(o.client_code, o.kg) for o in generate_scenario(name, list_clients(conn))]


def test_straight_line_order():
    pts = [Location(25.5, -103.4), Location(25.6, -103.3)]
    assert straight_line(pts) == [[-103.4, 25.5], [-103.3, 25.6]]


def test_plan_trips_carry_geometry(conn):
    replace_orders(conn, D, scenario_pairs(conn, "ligero"))
    out = run_planning(build_problem(conn, D), HaversineProvider(), geometry=straight_line)
    for v in out["vehicles"]:
        for t in v["trips"]:
            assert len(t["geometry"]) == len(t["stops"]) + 2
            assert t["geometry"][0] == [DEPOT.lon, DEPOT.lat]
            assert t["geometry"][-1] == [DEPOT.lon, DEPOT.lat]


def test_geometry_failure_does_not_break_plan(conn):
    replace_orders(conn, D, [("AARON", 1000)])

    def boom(points):
        raise RuntimeError("sin red")

    out = run_planning(build_problem(conn, D), HaversineProvider(), geometry=boom)
    assert out["vehicles"][0]["trips"][0]["geometry"] == []
    assert out["summary"]["served_kg"] == 1000


def test_ors_directions_uses_cache(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"features": [{"geometry": {"coordinates": [[1, 2], [3, 4]]}}]})

    d = OrsDirections("k", httpx.Client(transport=httpx.MockTransport(handler)), tmp_path)
    pts = [Location(2, 1), Location(4, 3)]
    assert d(pts) == [[1, 2], [3, 4]] and d(pts) == [[1, 2], [3, 4]]
    assert len(calls) == 1
    assert calls[0].url.path == "/v2/directions/driving-hgv/geojson"


def test_ors_directions_without_key_fails_only_when_called(tmp_path, monkeypatch):
    monkeypatch.delenv("ORS_API_KEY", raising=False)
    d = OrsDirections(cache_dir=tmp_path)
    with pytest.raises(RuntimeError, match="Falta ORS_API_KEY"):
        d([Location(2, 1), Location(4, 3)])


def test_make_geometry_by_provider(tmp_path):
    assert make_geometry(Settings(db_path=tmp_path / "x.db")) is straight_line
    assert isinstance(make_geometry(Settings(db_path=tmp_path / "x.db", provider="ors")), OrsDirections)


def test_app_trips_carry_geometry(client):
    client.post("/api/orders", json={"date": "2026-10-31", "client_code": "AARON", "kg": 500})
    client.app.state.recalc.wait_idle(60)
    plan = client.get("/api/plan?date=2026-10-31").json()["plan"]
    assert len(plan["vehicles"][0]["trips"][0]["geometry"]) == 3


def test_snap_without_key_exits_1(tmp_path, clients_file, monkeypatch, capsys):
    monkeypatch.delenv("ORS_API_KEY", raising=False)
    code = seed.main(["--clients", str(clients_file), "--db", str(tmp_path / "s.db"), "--snap"])
    assert code == 1 and "Falta ORS_API_KEY" in capsys.readouterr().err


def test_snap_moves_only_unverified(tmp_path, clients_file, monkeypatch):
    db = tmp_path / "s.db"
    seed.main(["--clients", str(clients_file), "--db", str(db)])
    conn = connect(db)
    verified = Client("AARON", "Aaron", "", Location(25.6, -103.4), LocationStatus.VERIFICADA)
    upsert_client(conn, verified)
    before = list_clients(conn)
    asked = {}

    class FakeOrs:
        def snap(self, points):
            asked.update(points)
            return {k: (None if k == "BETO" else Location(25.5, -103.5)) for k in points}

    monkeypatch.setattr(seed, "OrsProvider", FakeOrs)
    assert seed.main(["--clients", str(clients_file), "--db", str(db), "--snap"]) == 0
    assert "AARON" not in asked and len(asked) == 34
    assert get_client(conn, "AARON") == verified
    assert get_client(conn, "BETO").location == before["BETO"].location
    assert get_client(conn, "ADAN").location == Location(25.5, -103.5)
    assert get_client(conn, "ADAN").location_status == before["ADAN"].location_status
