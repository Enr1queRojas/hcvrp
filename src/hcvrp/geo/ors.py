from __future__ import annotations

import math
import os

import httpx

from hcvrp.domain import Location
from hcvrp.geo.matrix import Matrix

BASE = "https://api.openrouteservice.org/v2"


class OrsProvider:
    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None):
        self.api_key = api_key or os.environ.get("ORS_API_KEY") or os.environ.get("ORS_API")
        if not self.api_key:
            raise RuntimeError("Falta ORS_API_KEY")
        self.client = client or httpx.Client(timeout=60)

    def _post(self, path: str, body: dict) -> dict:
        try:
            r = self.client.post(f"{BASE}/{path}", json=body, headers={"Authorization": self.api_key})
        except httpx.RequestError as e:
            raise RuntimeError("no hay conexión con OpenRouteService") from e
        if r.status_code in (401, 403):
            raise RuntimeError("la clave de OpenRouteService no es válida")
        if r.status_code == 429:
            raise RuntimeError("se alcanzó el límite de consultas de OpenRouteService; intenta en un minuto")
        if r.is_error:
            raise RuntimeError(f"OpenRouteService respondió {r.status_code}")
        return r.json()

    def matrix(self, points: dict[str, Location]) -> Matrix:
        keys = list(points)
        data = self._post(
            "matrix/driving-hgv",
            {
                "locations": [[points[k].lon, points[k].lat] for k in keys],
                "metrics": ["distance", "duration"],
                "units": "km",
            },
        )
        dist, dur = data["distances"], data["durations"]
        n = len(keys)
        bad = [0] * n
        for i in range(n):
            for j in range(n):
                if dist[i][j] is None or dur[i][j] is None:
                    bad[i] += 1
                    bad[j] += 1
        if any(bad):
            worst = max(bad)
            culprits = ", ".join(k for k, c in zip(keys, bad) if c == worst)
            raise ValueError(f"Punto no ruteable en OpenRouteService: {culprits}")
        km_rows = [[float(v) for v in row] for row in dist]
        min_rows = [[math.ceil(s / 60) for s in row] for row in dur]
        return Matrix(keys, km_rows, min_rows)

    def snap(self, points: dict[str, Location], radius_m: int = 350) -> dict[str, Location | None]:
        keys = list(points)
        data = self._post(
            "snap/driving-hgv",
            {"locations": [[points[k].lon, points[k].lat] for k in keys], "radius": radius_m},
        )
        out: dict[str, Location | None] = {}
        for k, item in zip(keys, data["locations"]):
            out[k] = None if item is None else Location(item["location"][1], item["location"][0])
        return out
