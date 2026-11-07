from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env(path: Path = Path(".env")) -> None:
    """Carga un .env en el entorno. Lo definido en la terminal tiene prioridad."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        name, separator, value = line.strip().partition("=")
        if separator and name and not name.startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


@dataclass(frozen=True)
class Settings:
    db_path: Path = Path("data/hcvrp.db")
    provider: str = "haversine"
    cookie_secure: bool = False
    debounce_s: float = 1.5
    session_days: int = 30
    web_dist: Path = Path("web/dist")
    base_path: str = ""  # p. ej. "/rutas" cuando se publica en dominio/rutas

    @classmethod
    def from_env(cls) -> Settings:
        has_key = os.environ.get("ORS_API_KEY") or os.environ.get("ORS_API")
        return cls(
            db_path=Path(os.environ.get("HCVRP_DB", str(cls.db_path))),
            provider=os.environ.get("HCVRP_PROVIDER", "ors" if has_key else cls.provider),
            cookie_secure=os.environ.get("HCVRP_COOKIE_SECURE", "").lower() in ("1", "true"),
            debounce_s=float(os.environ.get("HCVRP_DEBOUNCE_S", cls.debounce_s)),
            web_dist=Path(os.environ.get("HCVRP_WEB_DIST", str(cls.web_dist))),
            base_path=normalize_base_path(os.environ.get("HCVRP_BASE_PATH", "")),
        )


def normalize_base_path(value: str) -> str:
    """'rutas', '/rutas/' y '/rutas' quedan como '/rutas'; vacío o '/' es la raíz."""
    value = value.strip().strip("/")
    return f"/{value}" if value else ""
