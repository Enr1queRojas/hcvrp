"""Geometría de las rutas para el mapa: línea recta u OpenRouteService con caché en disco."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx

from hcvrp.domain import Location
from hcvrp.geo.ors import OrsProvider


def straight_line(points: list[Location]) -> list[list[float]]:
    return [[p.lon, p.lat] for p in points]


class OrsDirections:
    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        cache_dir: Path = Path(".cache/directions"),
    ):
        self.api_key = api_key
        self.client = client
        self.cache_dir = Path(cache_dir)
        self._ors: OrsProvider | None = None

    def __call__(self, points: list[Location]) -> list[list[float]]:
        coordinates = straight_line(points)
        key = hashlib.sha256(json.dumps(coordinates).encode()).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        if self._ors is None:
            self._ors = OrsProvider(self.api_key, self.client)  # sin clave falla aquí, no al arrancar
        data = self._ors._post("directions/driving-hgv/geojson", {"coordinates": coordinates})
        geometry = data["features"][0]["geometry"]["coordinates"]
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(geometry), encoding="utf-8")
        return geometry
