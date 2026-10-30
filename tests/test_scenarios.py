import pytest

from hcvrp.scenarios import SCENARIOS, generate_scenario


@pytest.mark.parametrize("name,n,total", [("ligero", 12, 40_000), ("normal", 20, 80_000), ("pesado", 28, 120_000)])
def test_sizes_and_totals(clients, name, n, total):
    s = generate_scenario(name, clients)
    assert len(s) == n and len({o.client_code for o in s}) == n
    assert 0.85 * total <= sum(o.kg for o in s) <= 1.15 * total
    assert all(500 <= o.kg <= 15_000 and o.kg % 100 == 0 for o in s)
    assert [o.order_id for o in s] == [f"{name}-{i:02d}" for i in range(n)]


def test_inviable(clients):
    s = generate_scenario("inviable", clients)
    assert len(s) == 20 and sum(o.kg > 30_000 for o in s) == 1
    assert all(12_000 <= o.kg <= 15_000 for o in s if o.kg <= 30_000)
    assert len({o.client_code for o in s}) == 20


def test_deterministic(clients):
    assert generate_scenario("normal", clients) == generate_scenario("normal", clients)


def test_independent_of_insertion_order(clients):
    rev = dict(reversed(list(clients.items())))
    for name in SCENARIOS:
        assert generate_scenario(name, clients) == generate_scenario(name, rev)


def test_unknown_scenario(clients):
    with pytest.raises(ValueError):
        generate_scenario("xyz", clients)
