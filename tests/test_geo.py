import math

import httpx
import pytest

from hcvrp.domain import DEPOT, Location
from hcvrp.geo.cache import CachedProvider
from hcvrp.geo.matrix import HaversineProvider
from hcvrp.geo.ors import OrsProvider

PTS = {"DEPOT": DEPOT, "A": Location(25.54, -103.42)}


class CountingProvider:
    def __init__(self, inner):
        self.inner = inner
        self._n = 0

    @property
    def calls(self):
        return self._n

    def matrix(self, points):
        self._n += 1
        return self.inner.matrix(points)


def _client(payload):
    return httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload)))


@pytest.fixture
def ors_client():
    return _client({"distances": [[0, 5.2], [5.1, 0]], "durations": [[0, 601], [590, 0]]})


@pytest.fixture
def ors_client_with_null():
    return _client({"distances": [[0, None], [5.1, 0]], "durations": [[0, None], [590, 0]]})


@pytest.fixture
def ors_snap_client():
    return _client({"locations": [{"location": [-103.4201, 25.5402]}, None]})


def test_haversine_zero_and_symmetric():
    m = HaversineProvider().matrix({"DEPOT": DEPOT, "A": Location(25.54, -103.42), "B": DEPOT})
    assert m.km("DEPOT", "B") == 0 and m.minutes("DEPOT", "B") == 0
    assert m.km("DEPOT", "A") == m.km("A", "DEPOT") > 0
    assert m.minutes("DEPOT", "A") == math.ceil(m.km("DEPOT", "A") / 30 * 60)


def test_cache_calls_inner_once(tmp_path):
    inner = CountingProvider(HaversineProvider())
    c = CachedProvider(inner, tmp_path)
    assert c.matrix(PTS).km_rows == c.matrix(PTS).km_rows and inner.calls == 1


def test_cache_roundtrip_preserves_minutes(tmp_path):
    first = CachedProvider(HaversineProvider(), tmp_path).matrix(PTS)
    assert len(list(tmp_path.glob("*.json"))) == 1


    class Exploding(HaversineProvider):
        def matrix(self, points):
            raise AssertionError("inner must not be called on cache hit")

    Exploding.__name__ = "HaversineProvider"
    second = CachedProvider(Exploding(), tmp_path).matrix(PTS)
    assert first.min_rows == second.min_rows and first.km_rows == second.km_rows
    assert first.keys == second.keys


def test_cache_key_includes_provider_params(tmp_path):
    slow = CachedProvider(HaversineProvider(speed_kmh=30.0), tmp_path).matrix(PTS)
    fast = CachedProvider(HaversineProvider(speed_kmh=60.0), tmp_path).matrix(PTS)
    assert fast.min_rows != slow.min_rows
    assert fast.minutes("DEPOT", "A") < slow.minutes("DEPOT", "A")


def test_cache_returns_caller_key_order(tmp_path):
    c = CachedProvider(HaversineProvider(), tmp_path)
    m1 = c.matrix(PTS)
    rev = {"A": PTS["A"], "DEPOT": PTS["DEPOT"]}
    m2 = c.matrix(rev)
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert m2.keys == ["A", "DEPOT"]
    assert m2.km("DEPOT", "A") == m1.km("DEPOT", "A")
    assert m2.km_rows[0][1] == m1.km_rows[1][0]


def test_ors_requires_key(monkeypatch):
    monkeypatch.delenv("ORS_API_KEY", raising=False)
    monkeypatch.delenv("ORS_API", raising=False)
    with pytest.raises(RuntimeError, match="ORS_API_KEY"):
        OrsProvider()


def test_ors_matrix_parses_and_converts(ors_client):
    m = OrsProvider("k", client=ors_client).matrix(PTS)
    assert m.km("DEPOT", "A") == 5.2 and m.minutes("DEPOT", "A") == 11


def test_ors_unroutable_point_names_client(ors_client_with_null):
    with pytest.raises(ValueError, match="A"):
        OrsProvider("k", client=ors_client_with_null).matrix(PTS)


def test_ors_snap(ors_snap_client):
    r = OrsProvider("k", client=ors_snap_client).snap(
        {"A": Location(25.54, -103.42), "B": Location(25.0, -103.0)}
    )
    assert r["A"] == Location(25.5402, -103.4201) and r["B"] is None


@pytest.mark.parametrize("status,msg", [
    (401, "clave de OpenRouteService no es válida"),
    (403, "clave de OpenRouteService no es válida"),
    (429, "límite de consultas"),
    (500, "OpenRouteService respondió 500"),
])
def test_ors_errors_are_readable(status, msg):
    p = OrsProvider("k", httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status))))
    with pytest.raises(RuntimeError, match=msg):
        p.matrix({"DEPOT": Location(25.5, -103.4), "A": Location(25.6, -103.3)})


def test_ors_network_error_readable():
    def fail(request):
        raise httpx.ConnectError("x")

    p = OrsProvider("k", httpx.Client(transport=httpx.MockTransport(fail)))
    with pytest.raises(RuntimeError, match="no hay conexión"):
        p.matrix({"DEPOT": Location(25.5, -103.4), "A": Location(25.6, -103.3)})


def test_ors_accepts_key_under_either_name(monkeypatch):
    monkeypatch.delenv("ORS_API_KEY", raising=False)
    monkeypatch.setenv("ORS_API", "clave-corta")
    assert OrsProvider().api_key == "clave-corta"
    monkeypatch.setenv("ORS_API_KEY", "clave-larga")
    assert OrsProvider().api_key == "clave-larga"
