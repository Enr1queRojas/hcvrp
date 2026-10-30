from __future__ import annotations

import hashlib
import json
from pathlib import Path

from hcvrp.domain import Location
from hcvrp.geo.matrix import DistanceProvider, Matrix


class CachedProvider:
    def __init__(self, inner: DistanceProvider, cache_dir: Path = Path(".cache/matrix")):
        self.inner = inner
        self.cache_dir = Path(cache_dir)

    def _fingerprint(self) -> str:
        params = {
            k: v
            for k, v in vars(self.inner).items()
            if not k.startswith("_") and k != "api_key" and isinstance(v, (int, float, str, bool))
        }
        return type(self.inner).__name__ + json.dumps(params, sort_keys=True)

    def _key(self, points: dict[str, Location]) -> str:
        payload = {k: [v.lat, v.lon] for k, v in points.items()}
        raw = json.dumps(payload, sort_keys=True) + self._fingerprint()
        return hashlib.sha256(raw.encode()).hexdigest()

    def matrix(self, points: dict[str, Location]) -> Matrix:
        path = self.cache_dir / f"{self._key(points)}.json"
        if path.exists():
            d = json.loads(path.read_text(encoding="utf-8"))
            pos = {k: i for i, k in enumerate(d["keys"])}
            order = [pos[k] for k in points]
            return Matrix(
                list(points),
                [[d["km_rows"][i][j] for j in order] for i in order],
                [[d["min_rows"][i][j] for j in order] for i in order],
            )
        m = self.inner.matrix(points)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"keys": m.keys, "km_rows": m.km_rows, "min_rows": m.min_rows}),
            encoding="utf-8",
        )
        return m
