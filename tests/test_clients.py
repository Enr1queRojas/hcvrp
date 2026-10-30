from pathlib import Path

import pytest

from hcvrp.data.clients import (
    KEEP_PENDING, KEEP_WITH_ADDRESS, load_clients, prepare_clients, save_clients,
)
from hcvrp.domain import LocationStatus


@pytest.fixture
def fixture_path():
    return Path(__file__).parent / "fixtures" / "supuestos_min.json"


def test_filters_and_statuses(fixture_path):
    cs = {c.code: c for c in prepare_clients(fixture_path)}
    assert set(cs) == {"A.ESPARZA", "ADRIANA"}
    assert cs["A.ESPARZA"].location_status is LocationStatus.SINTETICA
    assert cs["ADRIANA"].location_status is LocationStatus.PENDIENTE
    assert all(c.location is not None for c in cs.values())


def test_coordinates_in_box_and_deterministic(fixture_path):
    a, b = prepare_clients(fixture_path), prepare_clients(fixture_path)
    assert a == b
    assert all(25.50 <= c.location.lat <= 25.60 and -103.52 <= c.location.lon <= -103.34 for c in a)


def test_keep_lists_sizes():
    assert len(KEEP_WITH_ADDRESS) == 27 and len(KEEP_PENDING) == 8


def test_roundtrip(tmp_path, fixture_path):
    cs = prepare_clients(fixture_path)
    save_clients(cs, tmp_path / "c.json")
    assert load_clients(tmp_path / "c.json") == {c.code: c for c in cs}
