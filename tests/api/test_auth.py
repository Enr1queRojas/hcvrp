from hcvrp.api.auth import hash_password, login, user_for_token, verify_password
from hcvrp.api.db import connect


def test_password_hash_roundtrip():
    h = hash_password("secreta123")
    assert h.startswith("scrypt$") and verify_password("secreta123", h)
    assert not verify_password("otra", h)
    assert hash_password("secreta123") != h  # sal aleatoria


def test_requires_login(anon):
    r = anon.get("/api/me")
    assert r.status_code == 401 and r.json()["detail"] == "inicia sesión"


def test_login_wrong_password(anon):
    r = anon.post("/api/login", json={"username": "ana", "password": "mal"})
    assert r.status_code == 401
    assert r.json()["detail"] == "usuario o contraseña incorrectos"


def test_login_unknown_user_same_message(anon):
    r = anon.post("/api/login", json={"username": "nadie", "password": "mal"})
    assert r.status_code == 401
    assert r.json()["detail"] == "usuario o contraseña incorrectos"


def test_login_me_logout(anon):
    r = anon.post("/api/login", json={"username": "ana", "password": "secreta123"})
    assert r.status_code == 200 and "hcvrp_session" in r.cookies
    assert "httponly" in r.headers["set-cookie"].lower()
    assert "samesite=lax" in r.headers["set-cookie"].lower()
    assert anon.get("/api/me").json() == {"username": "ana"}
    assert anon.post("/api/logout").status_code == 204
    assert anon.get("/api/me").status_code == 401


def test_logout_invalidates_token_server_side(settings, anon):
    anon.post("/api/login", json={"username": "ana", "password": "secreta123"})
    token = anon.cookies["hcvrp_session"]
    anon.post("/api/logout")
    assert user_for_token(connect(settings.db_path), token) is None


def test_expired_session_rejected(settings, anon):
    conn = connect(settings.db_path)
    token = login(conn, "ana", "secreta123", days=0)
    anon.cookies.set("hcvrp_session", token)
    assert anon.get("/api/me").status_code == 401
    assert conn.execute("SELECT 1 FROM sessions WHERE token = ?", (token,)).fetchone() is None
