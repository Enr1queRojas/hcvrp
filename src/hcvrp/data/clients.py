"""Depuración del JSON fuente de clientes y coordenadas sintéticas de La Laguna."""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from hcvrp.domain import (
    DEFAULT_CLOSES_AT, DEFAULT_OPENS_AT, Client, Location, LocationStatus, clock_to_minutes,
    minutes_to_clock,
)

KEEP_WITH_ADDRESS: frozenset[str] = frozenset({
    "A.ESPARZA", "A.ESPARZA3", "AARON", "ABSALON", "ADAN", "ADRIAN", "ANTUNEZ",
    "ARREDONDO", "ARREOLA", "BARBAS", "BEATRIZ", "BEATRIZ 2", "BENJA2", "BENJAMIN",
    "BERNARDO", "BETO", "BRETADO", "CABRERA", "CAMACHO", "CAMARILLO", "CAMBIO",
    "CAMBIO2", "CARLOS", "CARLOS C", "CARLOS2", "CAVAZOS", "CELIA CAR2",
})
KEEP_PENDING: frozenset[str] = frozenset({
    "ADRIANA", "ALAZAN", "APOLO", "AYUTLA", "BERNAL 2", "BUGARIN", "CAZEROLA", "CECY",
})

# (lat_min, lat_max, lon_min, lon_max): Torreón–Gómez–Lerdo
SYNTHETIC_BOX = (25.50, 25.60, -103.52, -103.34)


def prepare_clients(raw_path: Path, seed: int = 20261030) -> list[Client]:
    with open(raw_path, encoding="utf-8") as f:
        records = json.load(f)["clients"]
    keep = KEEP_WITH_ADDRESS | KEEP_PENDING
    by_code = {r["code"]: r for r in records if r["code"] in keep}
    lat_min, lat_max, lon_min, lon_max = SYNTHETIC_BOX
    rng = random.Random(seed)
    clients: list[Client] = []
    for code in sorted(by_code):
        r = by_code[code]
        lat = round(rng.uniform(lat_min, lat_max), 6)
        lon = round(rng.uniform(lon_min, lon_max), 6)
        status = (
            LocationStatus.SINTETICA if code in KEEP_WITH_ADDRESS else LocationStatus.PENDIENTE
        )
        clients.append(Client(
            code=code,
            name=r["name_original"],
            address=r["address_original"],
            location=Location(lat, lon),
            location_status=status,
        ))
    return clients


def synthetic_clients(seed: int = 20261030) -> dict[str, Client]:
    """Los 35 clientes con ubicaciones sintéticas y sin datos reales: para pruebas y mediciones."""
    lat_min, lat_max, lon_min, lon_max = SYNTHETIC_BOX
    rng = random.Random(seed)
    out: dict[str, Client] = {}
    for code in sorted(KEEP_WITH_ADDRESS | KEEP_PENDING):
        status = LocationStatus.SINTETICA if code in KEEP_WITH_ADDRESS else LocationStatus.PENDIENTE
        loc = Location(round(rng.uniform(lat_min, lat_max), 6), round(rng.uniform(lon_min, lon_max), 6))
        out[code] = Client(code, f"Cliente {code}", f"Dir {code}", loc, status)
    return out


def save_clients(clients: list[Client], path: Path) -> None:
    data = [
        {
            "code": c.code,
            "name": c.name,
            "address": c.address,
            "lat": c.location.lat if c.location else None,
            "lon": c.location.lon if c.location else None,
            "location_status": c.location_status.value,
            "opens_at": minutes_to_clock(c.opens_at),
            "closes_at": minutes_to_clock(c.closes_at),
            "blocked_vehicles": list(c.blocked_vehicles),
            "puesta": c.puesta,
        }
        for c in clients
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_clients(path: Path) -> dict[str, Client]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out: dict[str, Client] = {}
    for d in data:
        loc = None if d["lat"] is None or d["lon"] is None else Location(d["lat"], d["lon"])
        out[d["code"]] = Client(
            code=d["code"], name=d["name"], address=d["address"],
            location=loc, location_status=LocationStatus(d["location_status"]),
            opens_at=clock_to_minutes(d.get("opens_at") or minutes_to_clock(DEFAULT_OPENS_AT)),
            closes_at=clock_to_minutes(d.get("closes_at") or minutes_to_clock(DEFAULT_CLOSES_AT)),
            blocked_vehicles=tuple(d.get("blocked_vehicles") or ()),
            puesta=bool(d.get("puesta", False)),
        )
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("uso: python -m hcvrp.data.clients <fuente.json> <salida.json>", file=sys.stderr)
        return 2
    clients = prepare_clients(Path(argv[0]))
    save_clients(clients, Path(argv[1]))
    print(f"{len(clients)} clientes escritos en {argv[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
