"""Modelos de entrada y salida de la API."""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from hcvrp.domain import Client

LAGUNA_BOUNDS = (25.30, 25.80, -103.80, -103.10)  # (lat_min, lat_max, lon_min, lon_max)

ClientCode = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40, pattern=r"^[^/]+$")
]
ClientName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class ClientOut(BaseModel):
    code: str
    name: str
    address: str
    lat: float | None
    lon: float | None
    location_status: str

    @classmethod
    def of(cls, client: Client) -> ClientOut:
        loc = client.location
        return cls(
            code=client.code, name=client.name, address=client.address,
            lat=loc.lat if loc else None, lon=loc.lon if loc else None,
            location_status=client.location_status.value,
        )


class ClientIn(BaseModel):
    code: ClientCode
    name: ClientName
    address: str = ""


class ClientPatch(BaseModel):
    name: ClientName | None = None
    address: str | None = None


class LocationIn(BaseModel):
    lat: float
    lon: float

    @model_validator(mode="after")
    def inside_laguna(self) -> LocationIn:
        lat_min, lat_max, lon_min, lon_max = LAGUNA_BOUNDS
        if not (lat_min <= self.lat <= lat_max and lon_min <= self.lon <= lon_max):
            raise ValueError("la ubicación está fuera de La Laguna")
        return self


class VehicleIO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vehicle_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
    capacity_kg: int = Field(gt=0)
    km_per_liter: float = Field(gt=0)
    available: bool
    fixed_dispatch_cost_mxn: float = Field(ge=0)


class ParamsIO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    diesel_mxn_per_liter: float = Field(gt=0)
    loading_mxn_per_kg: float = Field(ge=0)
    shift_minutes: int = Field(ge=60, le=900)
    service_minutes: int = Field(ge=0, le=120)
    reload_minutes: int = Field(ge=0, le=480)
    max_trips_per_vehicle: int = Field(ge=1, le=6)
    time_limit_s: int = Field(ge=1, le=60)
