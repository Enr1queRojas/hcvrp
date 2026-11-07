import pytest

from hcvrp.domain import (
    DEPOT, Client, Location, LocationStatus, Order, Params, Problem,
)
from hcvrp.schedule import build_vehicle_plan, summarize

from fleets import TEST_FLEET


class TinyMatrix:
    _km = {("DEPOT", "A"): 5.0, ("A", "B"): 6.0, ("B", "DEPOT"): 8.0}
    _min = {("DEPOT", "A"): 10, ("A", "B"): 15, ("B", "DEPOT"): 20}

    @staticmethod
    def _get(table, a, b):
        if a == b:
            return 0
        return table.get((a, b), table.get((b, a)))

    def km(self, a, b):
        return self._get(self._km, a, b)

    def minutes(self, a, b):
        return self._get(self._min, a, b)


@pytest.fixture
def tiny_matrix():
    return TinyMatrix()


@pytest.fixture
def problem_ab():
    clients = {
        c: Client(c, f"Cliente {c}", f"Dir {c}", Location(25.53, -103.37), LocationStatus.SINTETICA)
        for c in ("A", "B")
    }
    orders = [Order("o1", "A", 3000), Order("o2", "B", 4000)]
    return Problem(DEPOT, clients, list(TEST_FLEET), orders, Params())


@pytest.fixture
def plan_ab(problem_ab, tiny_matrix):
    vp = build_vehicle_plan("V1", [problem_ab.orders], tiny_matrix, problem_ab.params)
    return summarize(problem_ab, [vp], [], tiny_matrix)


@pytest.fixture
def clients():
    import random

    from hcvrp.data.clients import KEEP_PENDING, KEEP_WITH_ADDRESS, SYNTHETIC_BOX

    lat_min, lat_max, lon_min, lon_max = SYNTHETIC_BOX
    rng = random.Random(20261030)
    out = {}
    for code in sorted(KEEP_WITH_ADDRESS | KEEP_PENDING):
        status = LocationStatus.SINTETICA if code in KEEP_WITH_ADDRESS else LocationStatus.PENDIENTE
        loc = Location(round(rng.uniform(lat_min, lat_max), 6), round(rng.uniform(lon_min, lon_max), 6))
        out[code] = Client(code, f"Cliente {code}", f"Dir {code}", loc, status)
    return out


@pytest.fixture
def problem_for(clients):
    from hcvrp.scenarios import generate_scenario

    def make(name: str) -> Problem:
        return Problem(
            DEPOT, clients, list(TEST_FLEET), generate_scenario(name, clients), Params(time_limit_s=5)
        )

    return make


@pytest.fixture
def clients_file(clients, tmp_path):
    from hcvrp.data.clients import save_clients

    path = tmp_path / "clients.json"
    save_clients(list(clients.values()), path)
    return path
