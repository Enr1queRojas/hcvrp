from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    db_path: Path = Path("data/hcvrp.db")
    provider: str = "haversine"
    cookie_secure: bool = False
    debounce_s: float = 1.5
    session_days: int = 30
    web_dist: Path = Path("web/dist")

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            db_path=Path(os.environ.get("HCVRP_DB", str(cls.db_path))),
            provider=os.environ.get("HCVRP_PROVIDER", cls.provider),
            cookie_secure=os.environ.get("HCVRP_COOKIE_SECURE", "").lower() in ("1", "true"),
            debounce_s=float(os.environ.get("HCVRP_DEBOUNCE_S", cls.debounce_s)),
            web_dist=Path(os.environ.get("HCVRP_WEB_DIST", str(cls.web_dist))),
        )
