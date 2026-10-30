"""Escenarios simulados de pedidos."""
from __future__ import annotations

import random

from hcvrp.domain import Client, Order

SCENARIOS = ("ligero", "normal", "pesado", "inviable")

_SPEC = {"ligero": (12, 40_000), "normal": (20, 80_000), "pesado": (28, 120_000)}
_MIN_KG, _MAX_KG = 500, 15_000
_TOLERANCE = 0.05  # objetivo de ajuste interno (la cota exigida es +-15 %)


def _round100(x: float) -> int:
    return int(round(x / 100.0)) * 100


def _scaled(raw: list[float], factor: float) -> list[int]:
    return [min(_MAX_KG, max(_MIN_KG, _round100(r * factor))) for r in raw]


def _sizes(rng: random.Random, n: int, target: int) -> list[int]:
    n_big = round(0.2 * n)
    raw = [rng.uniform(1_000, 6_000) for _ in range(n - n_big)]
    raw += [rng.uniform(8_000, 15_000) for _ in range(n_big)]
    rng.shuffle(raw)
    factor = target / sum(raw)
    best = _scaled(raw, factor)
    # El recorte rompe la proporcionalidad: reajustar el factor de forma determinista.
    for _ in range(50):
        total = sum(best)
        if abs(total - target) <= _TOLERANCE * target:
            break
        factor *= target / total
        best = _scaled(raw, factor)
    if abs(sum(best) - target) > 0.15 * target:
        raise ValueError(f"no se pudo ajustar el escenario al total objetivo {target}")
    return best


def generate_scenario(name: str, clients: dict[str, Client], seed: int = 20261030) -> list[Order]:
    if name not in SCENARIOS:
        raise ValueError(f"escenario desconocido: {name!r}; opciones: {SCENARIOS}")
    rng = random.Random(seed)
    codes = sorted(clients)
    if name == "inviable":
        n = 20
        if len(codes) < n:
            raise ValueError(f"se necesitan {n} clientes, hay {len(codes)}")
        chosen = rng.sample(codes, n)
        kgs = [35_000] + [_round100(rng.uniform(12_000, 15_000)) for _ in range(n - 1)]
        rng.shuffle(kgs)
    else:
        n, target = _SPEC[name]
        if len(codes) < n:
            raise ValueError(f"se necesitan {n} clientes, hay {len(codes)}")
        chosen = rng.sample(codes, n)
        kgs = _sizes(rng, n, target)
    return [Order(f"{name}-{i:02d}", code, kg) for i, (code, kg) in enumerate(zip(chosen, kgs))]
