from datetime import date

from fastapi.testclient import TestClient

from hcvrp.api.app import create_app
from hcvrp.api.db import connect
from hcvrp.api.planning import Recalculator, build_problem, inputs_hash, make_provider
from hcvrp.api.settings import Settings
from hcvrp.api.store import add_order, get_plan_row
from hcvrp.geo.matrix import HaversineProvider

D = "2026-10-31"
DAY = date(2026, 10, 31)


def test_scenario_triggers_plan(client):
    client.post("/api/orders/scenario", json={"date": D, "name": "normal"})
    assert client.app.state.recalc.wait_idle(120)
    body = client.get(f"/api/plan?date={D}").json()
    assert body["status"] == "listo" and body["stale"] is False
    assert body["plan"]["summary"]["served_kg"] > 0
    assert body["error"] is None and body["computed_at"]


def test_plan_requires_login(anon):
    assert anon.get(f"/api/plan?date={D}").status_code == 401
    assert anon.post(f"/api/plan/recalcular?date={D}").status_code == 401


def test_edit_marks_stale_then_refreshes(client):
    recalc = client.app.state.recalc
    client.post("/api/orders/scenario", json={"date": D, "name": "ligero"})
    recalc.wait_idle(120)
    first = client.get(f"/api/plan?date={D}").json()["computed_at"]
    recalc.pause()
    client.post("/api/orders", json={"date": D, "client_code": "AARON", "kg": 500})
    body = client.get(f"/api/plan?date={D}").json()
    assert body["stale"] is True and body["status"] == "calculando" and body["plan"] is not None
    recalc.resume()
    recalc.wait_idle(120)
    body = client.get(f"/api/plan?date={D}").json()
    assert body["stale"] is False and body["computed_at"] != first


def test_result_discarded_if_data_changed_during_compute(settings, monkeypatch):
    calls = []

    def fake_run(problem, provider, geometry=None):
        calls.append(1)
        if len(calls) == 1:
            add_order(connect(settings.db_path), DAY, "AARON", 1)
        return {"marca": len(calls)}

    monkeypatch.setattr("hcvrp.api.planning.run_planning", fake_run)
    add_order(connect(settings.db_path), DAY, "AARON", 1000)
    recalc = Recalculator(settings, HaversineProvider())
    recalc.request(DAY)
    assert recalc.wait_idle(30)
    recalc.stop()
    conn = connect(settings.db_path)
    row = get_plan_row(conn, DAY)
    assert len(calls) == 2 and row["result"] == {"marca": 2}
    assert row["inputs_hash"] == inputs_hash(build_problem(conn, DAY))


def test_impossible_lock_gives_error_and_keeps_last_plan(client):
    recalc = client.app.state.recalc
    client.post("/api/orders/scenario", json={"date": D, "name": "ligero"})
    recalc.wait_idle(120)
    fleet = client.get("/api/fleet").json()
    fleet[0]["available"] = False
    client.put("/api/fleet", json=fleet)
    oid = client.get(f"/api/orders?date={D}").json()[0]["id"]
    client.put(f"/api/orders/{oid}/lock", json={"vehicle_id": fleet[0]["vehicle_id"], "trip_no": 1})
    recalc.wait_idle(120)
    body = client.get(f"/api/plan?date={D}").json()
    assert body["status"] == "error" and "no está disponible" in body["error"]
    assert body["plan"] is not None and body["stale"] is True
    assert client.get("/api/me").status_code == 200


def test_unexpected_failure_keeps_thread_alive(settings, monkeypatch):
    def boom(problem, provider, geometry=None):
        raise KeyError("secreto interno")

    monkeypatch.setattr("hcvrp.api.planning.run_planning", boom)
    add_order(connect(settings.db_path), DAY, "AARON", 1000)
    recalc = Recalculator(settings, HaversineProvider())
    recalc.request(DAY)
    assert recalc.wait_idle(30)
    row = get_plan_row(connect(settings.db_path), DAY)
    assert row["status"] == "error" and row["error"] == "error interno al calcular el plan"
    monkeypatch.setattr("hcvrp.api.planning.run_planning", lambda p, q, geometry=None: {"marca": 1})
    add_order(connect(settings.db_path), DAY, "AARON", 1)
    recalc.request(DAY)
    assert recalc.wait_idle(30)
    recalc.stop()
    assert get_plan_row(connect(settings.db_path), DAY)["status"] == "listo"


def test_empty_day_has_no_plan(client):
    assert client.get("/api/plan?date=2030-01-01").json()["status"] == "ninguno"


def test_day_emptied_keeps_last_plan_as_stale(client):
    recalc = client.app.state.recalc
    o = client.post("/api/orders", json={"date": D, "client_code": "AARON", "kg": 500}).json()
    recalc.wait_idle(120)
    client.delete(f"/api/orders/{o['id']}")
    recalc.wait_idle(120)
    body = client.get(f"/api/plan?date={D}").json()
    assert body["status"] == "listo" and body["stale"] is True and body["plan"] is not None


def test_recalcular_forces_new_compute(client):
    recalc = client.app.state.recalc
    client.post("/api/orders", json={"date": D, "client_code": "AARON", "kg": 500})
    recalc.wait_idle(120)
    first = client.get(f"/api/plan?date={D}").json()["computed_at"]
    assert client.post(f"/api/plan/recalcular?date={D}").status_code == 202
    recalc.wait_idle(120)
    assert client.get(f"/api/plan?date={D}").json()["computed_at"] != first


def test_same_inputs_are_not_recomputed(client):
    recalc = client.app.state.recalc
    client.post("/api/orders", json={"date": D, "client_code": "AARON", "kg": 500})
    recalc.wait_idle(120)
    first = client.get(f"/api/plan?date={D}").json()["computed_at"]
    recalc.request(DAY)
    recalc.wait_idle(120)
    assert client.get(f"/api/plan?date={D}").json()["computed_at"] == first


def test_startup_plans_days_left_pending(settings):
    add_order(connect(settings.db_path), DAY, "AARON", 500)
    with TestClient(create_app(settings)) as c:
        assert c.app.state.recalc.wait_idle(60)
    assert get_plan_row(connect(settings.db_path), DAY)["status"] == "listo"


def test_missing_ors_key_becomes_plan_error(settings, monkeypatch):
    monkeypatch.delenv("ORS_API_KEY", raising=False)
    ors = Settings(db_path=settings.db_path, provider="ors", debounce_s=0)
    add_order(connect(settings.db_path), DAY, "AARON", 500)
    recalc = Recalculator(ors, make_provider(ors))
    recalc.request(DAY)
    assert recalc.wait_idle(30)
    recalc.stop()
    row = get_plan_row(connect(settings.db_path), DAY)
    assert row["status"] == "error" and row["error"] == "Falta ORS_API_KEY"
