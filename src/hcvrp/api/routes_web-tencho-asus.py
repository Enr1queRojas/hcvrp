"""Configuración para la web y archivos de la SPA."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from hcvrp.api.auth import current_user
from hcvrp.api.schemas import LAGUNA_BOUNDS
from hcvrp.domain import DEPOT

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


@router.get("/config")
def get_config(request: Request) -> dict:
    return {
        "depot": {"lat": DEPOT.lat, "lon": DEPOT.lon},
        "provider": request.app.state.settings.provider,
        "bounds": list(LAGUNA_BOUNDS),
    }


def mount_web(app: FastAPI, dist: Path, base: str = "") -> None:
    """Sin compilar la web, el servicio queda solo como API.

    La web pide todo con rutas relativas, así que bajo un prefijo debe abrirse con
    la diagonal final (/rutas/): sin ella se redirige.
    """
    index = dist / "index.html"
    if not index.exists():
        return
    if base:
        @app.get("/", include_in_schema=False)
        @app.get(base, include_in_schema=False)
        def to_base() -> RedirectResponse:
            return RedirectResponse(f"{base}/")

    if (dist / "assets").is_dir():
        app.mount(f"{base}/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get(base + "/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="no existe esa ruta")
        return FileResponse(index)
