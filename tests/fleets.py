"""Flota fija de las pruebas, independiente de la flota real en DEFAULT_FLEET."""
from hcvrp.domain import Vehicle

TEST_FLEET: list[Vehicle] = [
    Vehicle("V1", 10_000, 4.0),
    Vehicle("V2", 20_000, 2.8),
    Vehicle("V3", 20_000, 2.8),
    Vehicle("V4", 30_000, 2.2),
]
