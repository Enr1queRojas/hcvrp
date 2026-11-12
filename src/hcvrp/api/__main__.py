"""Arranque del servicio."""
from __future__ import annotations

import os
import sys

import uvicorn

from hcvrp.api.app import create_app
from hcvrp.api.settings import Settings, load_env

if __name__ == "__main__":
    # Mientras se calcula un plan, el hilo del solver casi no suelta el intérprete. Con el intervalo
    # de fábrica (5 ms) cada consulta de la pantalla tardaba de 0.3 a 0.7 s durante el cálculo;
    # cediendo el paso más seguido responde en centésimas, sin frenar la búsqueda.
    sys.setswitchinterval(0.0002)
    load_env()
    uvicorn.run(
        create_app(Settings.from_env()),
        host=os.environ.get("HCVRP_HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )
