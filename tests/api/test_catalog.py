import pytest


def test_list_clients(client):
    data = client.get("/api/clients").json()
    assert len(data) == 35 and data == sorted(data, key=lambda c: c["code"])


def test_catalog_requires_login(anon):
    assert anon.get("/api/clients").status_code == 401
    assert anon.get("/api/fleet").status_code == 401
    assert anon.get("/api/params").status_code == 401


def test_set_location_marks_verified(client):
    r = client.put("/api/clients/AARON/location", json={"lat": 25.54, "lon": -103.41})
    assert r.status_code == 200 and r.json()["location_status"] == "verificada"
    assert r.json()["lat"] == 25.54 and r.json()["lon"] == -103.41


def test_location_outside_laguna_rejected(client):
    r = client.put("/api/clients/AARON/location", json={"lat": 19.43, "lon": -99.13})
    assert r.status_code == 422 and "fuera de La Laguna" in r.text


def test_create_patch_delete_client(client):
    assert client.post("/api/clients", json={"code": "NUEVO", "name": "Nuevo"}).status_code == 201
    r = client.post("/api/clients", json={"code": "NUEVO", "name": "x"})
    assert r.status_code == 409 and r.json()["detail"] == "ya existe el cliente NUEVO"
    c = client.patch("/api/clients/NUEVO", json={"address": "Calle 1"}).json()
    assert c["address"] == "Calle 1" and c["location_status"] == "pendiente" and c["lat"] is None
    assert c["name"] == "Nuevo"
    assert client.delete("/api/clients/NUEVO").status_code == 204
    r = client.delete("/api/clients/NUEVO")
    assert r.status_code == 404 and r.json()["detail"] == "no existe el cliente NUEVO"


def test_patch_keeps_location(client):
    before = next(c for c in client.get("/api/clients").json() if c["code"] == "AARON")
    after = client.patch("/api/clients/AARON", json={"name": "Otro"}).json()
    assert after == {**before, "name": "Otro"}


@pytest.mark.parametrize("code", ["", "   ", "A/B", "X" * 41])
def test_invalid_client_code_rejected(client, code):
    assert client.post("/api/clients", json={"code": code, "name": "x"}).status_code == 422


def test_unknown_client_404(client):
    assert client.patch("/api/clients/NADIE", json={"name": "x"}).status_code == 404
    assert client.put("/api/clients/NADIE/location", json={"lat": 25.54, "lon": -103.41}).status_code == 404


def test_delete_client_with_orders_conflict(client):
    client.post("/api/orders", json={"date": "2026-10-31", "client_code": "AARON", "kg": 1000})
    r = client.delete("/api/clients/AARON")
    assert r.status_code == 409 and "tiene pedidos" in r.json()["detail"]


def test_fleet_mark_unavailable(client):
    fleet = client.get("/api/fleet").json()
    fleet[0]["available"] = False
    assert client.put("/api/fleet", json=fleet).status_code == 200
    assert client.get("/api/fleet").json()[0]["available"] is False


def test_fleet_rejects_bad_capacity_and_duplicates(client):
    fleet = client.get("/api/fleet").json()
    assert client.put("/api/fleet", json=[{**fleet[0], "capacity_kg": 0}]).status_code == 422
    assert client.put("/api/fleet", json=[fleet[0], fleet[0]]).status_code == 422
    assert client.put("/api/fleet", json=[]).status_code == 422
    assert client.get("/api/fleet").json() == fleet


def test_params_roundtrip_and_bounds(client):
    p = client.get("/api/params").json()
    assert client.put("/api/params", json={**p, "diesel_mxn_per_liter": 25.0}).status_code == 200
    assert client.get("/api/params").json()["diesel_mxn_per_liter"] == 25.0
    assert client.put("/api/params", json={**p, "time_limit_s": 0}).status_code == 422


def test_catalog_writes_notify_all_dates(client):
    calls = []
    client.app.state.on_change = calls.append
    client.put("/api/params", json=client.get("/api/params").json())
    client.put("/api/fleet", json=client.get("/api/fleet").json())
    client.put("/api/clients/AARON/location", json={"lat": 25.54, "lon": -103.41})
    assert calls == [None, None, None]


def test_client_with_orders_can_be_edited_and_located(client):
    client.post("/api/orders", json={"date": "2026-10-31", "client_code": "AARON", "kg": 1000})
    assert client.put("/api/clients/AARON/location", json={"lat": 25.54, "lon": -103.41}).status_code == 200
    assert client.patch("/api/clients/AARON", json={"name": "Otro"}).status_code == 200
    assert client.get("/api/orders?date=2026-10-31").json()[0]["client_name"] == "Otro"


def test_clients_have_default_hours(client):
    c = client.get("/api/clients").json()[0]
    assert (c["opens_at"], c["closes_at"]) == ("09:00", "18:00")


def test_client_hours_can_change(client):
    r = client.patch("/api/clients/AARON", json={"opens_at": "10:00", "closes_at": "14:30"})
    assert r.status_code == 200 and (r.json()["opens_at"], r.json()["closes_at"]) == ("10:00", "14:30")
    r = client.patch("/api/clients/AARON", json={"closes_at": "09:30"})  # cerraría antes de abrir
    assert r.status_code == 422 and "abrir antes de cerrar" in r.json()["detail"]
    r = client.patch("/api/clients/AARON", json={"opens_at": "25:00"})
    assert r.status_code == 422


def test_new_client_hours(client):
    r = client.post("/api/clients", json={"code": "NUEVO", "name": "Nuevo", "opens_at": "08:00", "closes_at": "13:00"})
    assert r.status_code == 201 and (r.json()["opens_at"], r.json()["closes_at"]) == ("08:00", "13:00")


def test_blocked_trucks_on_client(client):
    assert client.get("/api/clients").json()[0]["blocked_vehicles"] == []
    r = client.patch("/api/clients/AARON", json={"blocked_vehicles": ["V3", "V1"]})
    assert r.status_code == 200 and r.json()["blocked_vehicles"] == ["V1", "V3"]
    r = client.patch("/api/clients/AARON", json={"blocked_vehicles": ["NOEXISTE"]})
    assert r.status_code == 422 and "NOEXISTE" in r.json()["detail"]
    r = client.patch("/api/clients/AARON", json={"name": "Aaron 2"})  # otros cambios no la borran
    assert r.json()["blocked_vehicles"] == ["V1", "V3"]


def test_client_puesta_flag(client):
    assert client.get("/api/clients").json()[0]["puesta"] is False
    r = client.patch("/api/clients/AARON", json={"puesta": True})
    assert r.status_code == 200 and r.json()["puesta"] is True
    assert client.patch("/api/clients/AARON", json={"name": "Otro"}).json()["puesta"] is True
