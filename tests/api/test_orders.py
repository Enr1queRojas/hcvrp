from datetime import date

import pytest

from hcvrp.scenarios import generate_scenario

D = "2026-10-31"


def add(client, code="AARON", kg=3000, day=D):
    return client.post("/api/orders", json={"date": day, "client_code": code, "kg": kg})


def test_add_and_sum_orders(client):
    a = add(client).json()
    b = add(client, kg=1500).json()
    assert a["id"] == b["id"] and b["kg"] == 4500
    assert [o["kg"] for o in client.get(f"/api/orders?date={D}").json()] == [4500]


def test_order_out_fields(client):
    r = add(client)
    assert r.status_code == 201
    body = r.json()
    assert body["date"] == D and body["client_code"] == "AARON" and body["lock"] is None
    assert body["client_name"] == "Cliente AARON"


def test_orders_require_login(anon):
    assert anon.get(f"/api/orders?date={D}").status_code == 401


@pytest.mark.parametrize("kg", [0, -5, 12.5, "mil", True, 1_000_001])
def test_invalid_kg_rejected(client, kg):
    r = add(client, kg=kg)
    assert r.status_code == 422
    assert r.json()["detail"] == "los kg deben ser un número entero entre 1 y 1000000"
    assert client.get(f"/api/orders?date={D}").json() == []


def test_validation_errors_are_in_spanish(client):
    r = client.post("/api/orders", json={"client_code": "AARON", "kg": 100})
    assert r.status_code == 422 and r.json()["detail"] == "la fecha no es válida"


def test_catalog_validation_speaks_the_users_language(client):
    params = client.get("/api/params").json()
    r = client.put("/api/params", json={**params, "time_limit_s": 0})
    assert r.json()["detail"] == "el tiempo máximo de cálculo debe estar entre 1 y 60 segundos"
    fleet = client.get("/api/fleet").json()
    r = client.put("/api/fleet", json=[{**fleet[0], "capacity_kg": 0}])
    assert r.json()["detail"] == "la capacidad debe ser mayor que 0"


def test_unknown_client_404(client):
    r = add(client, code="NADIE", kg=100)
    assert r.status_code == 404 and r.json()["detail"] == "no existe el cliente NADIE"


def test_patch_and_delete_order(client):
    o = add(client).json()
    assert client.patch(f"/api/orders/{o['id']}", json={"kg": 700}).json()["kg"] == 700
    assert client.patch(f"/api/orders/{o['id']}", json={"kg": 0}).status_code == 422
    assert client.delete(f"/api/orders/{o['id']}").status_code == 204
    assert client.delete(f"/api/orders/{o['id']}").status_code == 404
    assert client.patch(f"/api/orders/{o['id']}", json={"kg": 700}).status_code == 404


def test_scenarios_listed(client):
    assert client.get("/api/scenarios").json() == ["ligero", "normal", "pesado", "inviable"]


def test_load_scenario_replaces_day(client, clients):
    add(client, kg=999)
    r = client.post("/api/orders/scenario", json={"date": D, "name": "ligero"})
    assert r.status_code == 200
    expected = sorted((o.client_code, o.kg) for o in generate_scenario("ligero", clients))
    assert sorted((o["client_code"], o["kg"]) for o in r.json()) == expected
    assert client.get(f"/api/orders?date={D}").json() == r.json()


def test_unknown_scenario_rejected(client):
    r = client.post("/api/orders/scenario", json={"date": D, "name": "raro"})
    assert r.status_code == 422 and "raro" in r.json()["detail"]


def test_lock_validation_and_cascade(client):
    o = add(client).json()
    r = client.put(f"/api/orders/{o['id']}/lock", json={"vehicle_id": "V9", "trip_no": 1})
    assert r.status_code == 422 and r.json()["detail"] == "no existe el camión V9"
    r = client.put(f"/api/orders/{o['id']}/lock", json={"vehicle_id": "V2", "trip_no": 4})
    assert r.status_code == 422 and r.json()["detail"] == "el viaje debe estar entre 1 y 3"
    assert client.put(f"/api/orders/{o['id']}/lock", json={"vehicle_id": "V2", "trip_no": 2}).status_code == 200
    assert client.get(f"/api/orders?date={D}").json()[0]["lock"] == {"vehicle_id": "V2", "trip_no": 2, "position": None}
    assert client.delete(f"/api/orders/{o['id']}").status_code == 204
    assert client.get(f"/api/orders?date={D}").json() == []


def test_lock_can_be_removed(client):
    o = add(client).json()
    client.put(f"/api/orders/{o['id']}/lock", json={"vehicle_id": "V2", "trip_no": 2})
    assert client.delete(f"/api/orders/{o['id']}/lock").status_code == 204
    assert client.get(f"/api/orders?date={D}").json()[0]["lock"] is None


def test_lock_on_unknown_order_404(client):
    r = client.put("/api/orders/999/lock", json={"vehicle_id": "V2", "trip_no": 1})
    assert r.status_code == 404


def test_order_writes_notify_their_date(client):
    calls = []
    client.app.state.on_change = calls.append
    day = date(2026, 10, 31)
    o = add(client).json()
    client.patch(f"/api/orders/{o['id']}", json={"kg": 700})
    client.put(f"/api/orders/{o['id']}/lock", json={"vehicle_id": "V2", "trip_no": 1})
    client.delete(f"/api/orders/{o['id']}/lock")
    client.delete(f"/api/orders/{o['id']}")
    client.post("/api/orders/scenario", json={"date": D, "name": "ligero"})
    assert calls == [day] * 6


def test_lock_truck_only(client):
    o = add(client).json()
    r = client.put(f"/api/orders/{o['id']}/lock", json={"vehicle_id": "V2"})
    assert r.status_code == 200
    assert client.get(f"/api/orders?date={D}").json()[0]["lock"] == {
        "vehicle_id": "V2", "trip_no": None, "position": None,
    }


def test_sequence_endpoint(client):
    a = add(client).json()
    b = add(client, code="BETO", kg=500).json()
    r = client.put("/api/orders/sequence", json={"date": D, "vehicle_id": "V1", "trips": [[b["id"], a["id"]]]})
    assert r.status_code == 204
    locks = {o["id"]: o["lock"] for o in client.get(f"/api/orders?date={D}").json()}
    assert locks[b["id"]] == {"vehicle_id": "V1", "trip_no": 1, "position": 1}
    assert locks[a["id"]] == {"vehicle_id": "V1", "trip_no": 1, "position": 2}
    assert client.delete(f"/api/orders/sequence?date={D}&vehicle_id=V1").status_code == 204
    assert all(o["lock"] is None for o in client.get(f"/api/orders?date={D}").json())


@pytest.mark.parametrize("trips,detail", [
    ([[]], "no trae pedidos"),
    ([[1, 1]], "más de una vez"),
    ([[999]], "no son de ese día"),
    ([[1], [2], [3], [4]], "a lo más"),
])
def test_sequence_rejects_bad_input(client, trips, detail):
    add(client)
    r = client.put("/api/orders/sequence", json={"date": D, "vehicle_id": "V1", "trips": trips})
    assert r.status_code == 422 and detail in r.json()["detail"]


def test_sequence_unknown_truck(client):
    o = add(client).json()
    r = client.put("/api/orders/sequence", json={"date": D, "vehicle_id": "XX", "trips": [[o["id"]]]})
    assert r.status_code == 422
