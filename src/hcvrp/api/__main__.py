"""Arranque del servicio."""
from __future__ import annotations

import os

import uvicorn

from hcvrp.api.app import create_app
from hcvrp.api.settings import Settings

if __name__ == "__main__":
    uvicorn.run(
        create_app(Settings.from_env()),
        host=os.environ.get("HCVRP_HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )
