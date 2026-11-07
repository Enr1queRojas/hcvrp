import pytest
from fastapi.testclient import TestClient

from hcvrp.api import seed
from hcvrp.api.app import create_app
from hcvrp.api.auth import create_user
from hcvrp.api.db import connect
from hcvrp.api.settings import Settings
from hcvrp.api.store import set_fleet, set_params
from hcvrp.domain import Params

from fleets import TEST_FLEET


@pytest.fixture
def settings(tmp_path, clients_file):
    db = tmp_path / "api.db"
    assert seed.main(["--clients", str(clients_file), "--db", str(db)]) == 0
    conn = connect(db)
    set_fleet(conn, TEST_FLEET)
    set_params(conn, Params(time_limit_s=1))
    create_user(conn, "ana", "secreta123")
    conn.close()
    return Settings(db_path=db, debounce_s=0)


@pytest.fixture
def anon(settings):
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def client(anon):
    r = anon.post("/api/login", json={"username": "ana", "password": "secreta123"})
    assert r.status_code == 200
    return anon
