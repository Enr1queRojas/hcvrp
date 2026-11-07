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


SHIFT_START_MIN = 9 * 60  # la jornada arranca a las 09:00; los minutos de jornada cuentan desde ahí
DEFAULT_OPENS_AT = 9 * 60  # horario de recepción de los clientes, en minutos desde la medianoche
DEFAULT_CLOSES_AT = 18 * 60


def clock_to_minutes(value: str) -> int:
    """De "HH:MM" a minutos desde la medianoche."""
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def minutes_to_clock(value: int) -> str:
    return f"{value // 60:02d}:{value % 60:02d}"


@dataclass(frozen=True)
class Client:
    code: str
    name: str
    address: str
    location: Location | None
    location_status: LocationStatus
    # Horario en que el cliente recibe, en minutos desde la medianoche. Es firme: la entrega
    # debe empezar después de abrir y terminar antes de cerrar.
    opens_at: int = DEFAULT_OPENS_AT
    closes_at: int = DEFAULT_CLOSES_AT

    def __post_init__(self) -> None:
        if not 0 <= self.opens_at < self.closes_at <= 24 * 60:
            raise ValueError(
                f"horario inválido para el cliente {self.code!r}: abre {self.opens_at}, cierra {self.closes_at}"
            )


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
    # Horario de entrega opcional, en minutos desde el inicio de la jornada (09:00).
    # window_start: no se entrega antes (el camión espera). window_end: se procura entregar a
    # más tardar a esa hora; si no se puede, se entrega tarde y el plan lo marca.
    window_start: int | None = None
    window_end: int | None = None

    def __post_init__(self) -> None:
        if self.kg <= 0:
            raise ValueError(f"kg must be > 0 for order {self.order_id!r}, got {self.kg}")
        for name in ("window_start", "window_end"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be >= 0 for order {self.order_id!r}, got {value}")
        if (
            self.window_start is not None
            and self.window_end is not None
            and self.window_start >= self.window_end
        ):
            raise ValueError(
                f"window_start must be before window_end for order {self.order_id!r}, "
                f"got {self.window_start} >= {self.window_end}"
            )

    @property
    def has_window(self) -> bool:
        return self.window_start is not None or self.window_end is not None


class UnservedReason(StrEnum):
    EXCEDE_CAPACIDAD = "excede_capacidad"
    NO_CABE_JORNADA = "no_cabe_jornada"
    FUERA_HORARIO_CLIENTE = "fuera_horario_cliente"
    SIN_COORDENADAS = "sin_coordenadas"
    SATURACION_FLOTA = "saturacion_flota"


@dataclass(frozen=True)
class Stop:
    order_id: str
    client_code: str
    kg: int
    arrival_min: int  # inicio de la entrega (después de esperar, si llegó antes de su horario)
    departure_min: int
    wait_min: int = 0  # minutos que esperó por llegar antes de window_start
    window_start: int | None = None
    window_end: int | None = None

    @property
    def late_min(self) -> int:
        """Minutos de retraso respecto a window_end (0 si llegó a tiempo o no tiene horario)."""
        return 0 if self.window_end is None else max(0, self.arrival_min - self.window_end)


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
