from __future__ import annotations

import math
from typing import Protocol

from hcvrp.domain import Location


class Matrix:
    def __init__(self, keys: list[str], km_rows: list[list[float]], min_rows: list[list[int]]):
        self.keys = list(keys)
        self.km_rows = km_rows
        self.min_rows = min_rows
        self._idx = {k: i for i, k in enumerate(self.keys)}

    def km(self, a: str, b: str) -> float:
        return self.km_rows[self._idx[a]][self._idx[b]]

    def minutes(self, a: str, b: str) -> int:
        return self.min_rows[self._idx[a]][self._idx[b]]


class DistanceProvider(Protocol):
    def matrix(self, points: dict[str, Location]) -> Matrix: ...


def haversine_km(a: Location, b: Location) -> float:
    r = 6371.0088
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lon - a.lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


class HaversineProvider:
    def __init__(self, detour_factor: float = 1.3, speed_kmh: float = 30.0):
        self.detour_factor = detour_factor
        self.speed_kmh = speed_kmh

    def matrix(self, points: dict[str, Location]) -> Matrix:
        keys = list(points)
        km_rows = [
            [haversine_km(points[a], points[b]) * self.detour_factor for b in keys] for a in keys
        ]
        min_rows = [[math.ceil(k / self.speed_kmh * 60) for k in row] for row in km_rows]
        return Matrix(keys, km_rows, min_rows)
