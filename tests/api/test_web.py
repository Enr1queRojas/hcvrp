from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from hcvrp.api.app import create_app
from hcvrp.api.db import connect
from hcvrp.api.planning import PlanningError, build_problem, inputs_hash, run_planning
from hcvrp.api.store import add_order, set_lock
from hcvrp.domain import DEPOT
from hcvrp.geo.matrix import HaversineProvider

LOGIN_OK = {"username": "ana", "password": "secreta123"}
LOGIN_BAD = {"username": "ana", "password": "mal"}


def test_config_returns_depot(client):
    body = client.get("/api/config").json()
    assert body["depot"] == {"lat": DEPOT.lat, "lon": DEPOT.lon}
    assert body["provider"] == "haversine"
    assert body["bounds"] == [25.30, 25.80, -103.80, -103.10]


def test_config_requires_login(anon):
    assert anon.get("/api/config").status_code == 401


def test_login_blocked_after_5_failures(anon):
    for _ in range(5):
        assert anon.post("/api/login", json=LOGIN_BAD).status_code == 401
    r = anon.post("/api/login", json=LOGIN_OK)
    assert r.status_code == 429 and r.json()["detail"] == "demasiados intentos; espera 15 minutos"


def test_login_success_clears_failures(anon):
    for _ in range(4):
        anon.post("/api/login", json=LOGIN_BAD)
    assert anon.post("/api/login", json=LOGIN_OK).status_code == 200
    for _ in range(4):
        assert anon.post("/api/login", json=LOGIN_BAD).status_code == 401
    assert anon.post("/api/login", json=LOGIN_OK).status_code == 200


def test_impossible_lock_names_client(settings):
    conn = connect(settings.db_path)
    day = date(2026, 10, 31)
    order = add_order(conn, day, "AARON", 25_000)  # no cabe en V1 (10 000 kg)
    set_lock(conn, int(order.order_id), "V1", 1)
    with pytest.raises(PlanningError) as e:
        run_planning(build_problem(conn, day), HaversineProvider())
    message = str(e.value)
    assert "Cliente AARON" in message and f"'{order.order_id}'" not in message
    assert "infeasible" not in message


def test_impossible_lock_explains_reason(settings):
    conn = connect(settings.db_path)
    day = date(2026, 10, 31)
    order = add_order(conn, day, "AARON", 40_000)  # no cabe en ningún camión
    set_lock(conn, int(order.order_id), "V4", 1)
    with pytest.raises(PlanningError, match="excede la capacidad de todos los camiones"):
        run_planning(build_problem(conn, day), HaversineProvider())


def test_hash_changes_with_provider(settings):
    conn = connect(settings.db_path)
    add_order(conn, date(2026, 10, 31), "AARON", 1000)
    problem = build_problem(conn, date(2026, 10, 31))
    assert inputs_hash(problem, "ors") != inputs_hash(problem, "haversine")


@pytest.fixture
def dist(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>hcvrp</html>", encoding="utf-8")
    (root / "assets" / "a.js").write_text("let a", encoding="utf-8")
    return root


def test_spa_served_and_api_404_stays_json(settings, dist):
    with TestClient(create_app(replace(settings, web_dist=dist))) as c:
        assert "hcvrp" in c.get("/").text
        assert "hcvrp" in c.get("/cualquier/ruta").text
        assert c.get("/assets/a.js").text == "let a"
        r = c.get("/api/nada")
        assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")


def test_no_dist_means_api_only(settings, tmp_path):
    with TestClient(create_app(replace(settings, web_dist=tmp_path / "no-existe"))) as c:
        assert c.get("/").status_code == 404
        assert c.get("/api/me").status_code == 401
