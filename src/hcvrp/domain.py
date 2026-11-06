from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


@dataclass(frozen=True)
class Location:
    lat: float
    lon: float


class LocationStatus(StrEnum):
    SINTETICA = "sintetica"
    PENDIENTE = "pendiente"
    VERIFICADA = "verificada"


@dataclass(frozen=True)
class Client:
    code: str
    name: str
    address: str
    location: Location | None
    location_status: LocationStatus


@dataclass(frozen=True)
class Vehicle:
    vehicle_id: str
    capacity_kg: int
    km_per_liter: float
    available: bool = True
    fixed_dispatch_cost_mxn: float = 0.0

    def __post_init__(self) -> None:
        if self.capacity_kg <= 0:
            raise ValueError(
                f"la capacidad debe ser > 0 en el camión {self.vehicle_id!r}, recibida {self.capacity_kg}"
            )
        if self.km_per_liter <= 0:
            raise ValueError(
                f"el rendimiento (km/L) debe ser > 0 en el camión {self.vehicle_id!r}, "
                f"recibido {self.km_per_liter}"
            )


@dataclass(frozen=True)
class Params:
    diesel_mxn_per_liter: float = 27.0
    loading_mxn_per_kg: float = 0.10
    shift_minutes: int = 480
    service_minutes: int = 20
    reload_minutes: int = 120
    max_trips_per_vehicle: int = 3
    time_limit_s: int = 15


@dataclass(frozen=True)
class Order:
    order_id: str
    client_code: str
    kg: int

    def __post_init__(self) -> None:
        if self.kg <= 0:
            raise ValueError(f"kg must be > 0 for order {self.order_id!r}, got {self.kg}")


class UnservedReason(StrEnum):
    EXCEDE_CAPACIDAD = "excede_capacidad"
    NO_CABE_JORNADA = "no_cabe_jornada"
    SIN_COORDENADAS = "sin_coordenadas"
    SATURACION_FLOTA = "saturacion_flota"


@dataclass(frozen=True)
class Stop:
    order_id: str
    client_code: str
    kg: int
    arrival_min: int
    departure_min: int


@dataclass(frozen=True)
class Trip:
    trip_no: int
    start_min: int
    end_min: int
    km: float
    stops: tuple[Stop, ...]

    @property
    def kg(self) -> int:
        return sum(s.kg for s in self.stops)


@dataclass(frozen=True)
class VehiclePlan:
    vehicle_id: str
    trips: tuple[Trip, ...]


@dataclass(frozen=True)
class Unserved:
    order_id: str
    reason: UnservedReason


@dataclass(frozen=True)
class Plan:
    vehicles: tuple[VehiclePlan, ...]
    unserved: tuple[Unserved, ...]
    cost_mxn: float
    km_total: float
    liters_total: float
    reloads: int
    uses_unverified_locations: bool


@dataclass
class Problem:
    depot: Location
    clients: dict[str, Client]
    vehicles: list[Vehicle]
    orders: list[Order]
    params: Params
    # Bloqueos: pedido -> (camión, viaje); viaje None = solo el camión, el plan elige el viaje.
    locks: dict[str, tuple[str, int | None]] = field(default_factory=dict)
    # Orden a mano: pedido -> posición dentro de su viaje bloqueado (1, 2, ...). Solo cuenta el
    # orden relativo entre los pedidos con posición del mismo (camión, viaje).
    positions: dict[str, int] = field(default_factory=dict)


DEPOT = Location(lat=25.528580, lon=-103.373271)

# Flota de Graneros Guerra. Rendimientos (km/L) estimados por tamaño; se ajustan en la app.
DEFAULT_FLEET: list[Vehicle] = [
    Vehicle("Leña", 10_000, 4.0),
    Vehicle("Soriano", 10_000, 4.0),
    Vehicle("Corto", 5_000, 5.0),
    Vehicle("Guinda", 20_000, 2.8),
    Vehicle("Volvo", 20_000, 2.8),
    Vehicle("Mercedes", 15_000, 3.3),
]
