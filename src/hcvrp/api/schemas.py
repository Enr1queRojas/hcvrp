"""Modelos de entrada y salida de la API."""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date as Date
from typing import Annotated, Any

from pydantic import (
    BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, model_validator,
)

from hcvrp.baseline import Comparison, served_kg
from hcvrp.cli import REASONS_ES
from hcvrp.precheck import merge_orders
from hcvrp.domain import (
    Client, Location, LocationStatus, Plan, Problem, Trip, clock_to_minutes, minutes_to_clock,
)

logger = logging.getLogger(__name__)

LAGUNA_BOUNDS = (25.30, 25.80, -103.80, -103.10)  # (lat_min, lat_max, lon_min, lon_max)
MAX_ORDER_KG = 1_000_000

GeometryFn = Callable[[list[Location]], list[list[float]]]

ClientCode = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40, pattern=r"^[^/]+$")
]
ClientName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Clock = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]  # "HH:MM"


class ClientOut(BaseModel):
    code: str
    name: str
    address: str
    lat: float | None
    lon: float | None
    location_status: str
    opens_at: str  # "HH:MM": el cliente recibe a partir de esta hora
    closes_at: str  # "HH:MM": la entrega debe terminar antes de esta hora
    blocked_vehicles: list[str]  # camiones que no pueden entrar con este cliente
    puesta: bool  # en urgencia acepta solo 10-15% de su pedido; el resto pasa a otro día

    @classmethod
    def of(cls, client: Client) -> ClientOut:
        loc = client.location
        return cls(
            code=client.code, name=client.name, address=client.address,
            lat=loc.lat if loc else None, lon=loc.lon if loc else None,
            location_status=client.location_status.value,
            opens_at=minutes_to_clock(client.opens_at), closes_at=minutes_to_clock(client.closes_at),
            blocked_vehicles=list(client.blocked_vehicles), puesta=client.puesta,
        )


class _Hours(BaseModel):
    @model_validator(mode="after")
    def _ordered_hours(self):
        opens, closes = getattr(self, "opens_at", None), getattr(self, "closes_at", None)
        if opens is not None and closes is not None and opens >= closes:
            raise ValueError("el horario del cliente debe abrir antes de cerrar")
        return self


class ClientIn(_Hours):
    code: ClientCode
    name: ClientName
    address: str = ""
    opens_at: Clock = "09:00"
    closes_at: Clock = "18:00"
    blocked_vehicles: list[str] = []
    puesta: bool = False


class ClientPatch(_Hours):
    name: ClientName | None = None
    address: str | None = None
    opens_at: Clock | None = None
    closes_at: Clock | None = None
    blocked_vehicles: list[str] | None = None
    puesta: bool | None = None


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


def _check_kg(value: Any) -> int:
    if type(value) is not int or not 1 <= value <= MAX_ORDER_KG:
        raise ValueError(f"los kg deben ser un número entero entre 1 y {MAX_ORDER_KG}")
    return value


Kg = Annotated[int, BeforeValidator(_check_kg)]


Minute = Annotated[int, Field(ge=0, le=24 * 60)]  # minutos desde el inicio de la jornada (09:00)


class _Window(BaseModel):
    window_start: Minute | None = None  # no entregar antes
    window_end: Minute | None = None  # entregar a más tardar (si no se puede, se entrega tarde)

    @model_validator(mode="after")
    def _ordered(self):
        if (
            self.window_start is not None
            and self.window_end is not None
            and self.window_start >= self.window_end
        ):
            raise ValueError("el horario de entrega debe empezar antes de terminar")
        return self


class OrderIn(_Window):
    date: Date
    client_code: str
    kg: Kg


class OrderPatch(_Window):
    """Solo cambia lo que se manda: kg, o el horario (ambos campos; null quita ese extremo)."""
    kg: Kg | None = None


class LockIO(BaseModel):
    vehicle_id: str
    trip_no: int | None = Field(default=None, ge=1)  # None: solo el camión, el plan elige el viaje


class LockOut(LockIO):
    position: int | None = None  # posición dentro del viaje cuando el orden se fijó a mano


class SequenceIn(BaseModel):
    date: Date
    vehicle_id: str
    trips: list[list[int]]  # ids de pedido por viaje, en el orden de entrega


class OrderOut(BaseModel):
    id: int
    date: Date
    client_code: str
    client_name: str
    kg: int
    window_start: int | None = None
    window_end: int | None = None
    lock: LockOut | None


class ScenarioIn(BaseModel):
    date: Date
    name: str


class PlanSummary(BaseModel):
    cost_mxn: float
    km_total: float
    liters_total: float
    reloads: int
    vehicles_used: int
    served_kg: int
    unserved_kg: int
    late_stops: int = 0  # paradas que no se alcanzaron a entregar dentro de su horario
    puesta_stops: int = 0  # paradas que llevan solo una parte del pedido (puesta)


class AfternoonLoad(BaseModel):
    vehicle_id: str
    kg: int
    orders: int
    capacity_pct: float


class StopOut(BaseModel):
    order_id: str
    client_code: str
    client_name: str
    kg: int
    arrival_min: int
    departure_min: int
    ordered_kg: int = 0  # kilos del pedido; mayor que kg cuando se entrega en puesta
    wait_min: int = 0
    window_start: int | None = None
    window_end: int | None = None
    late_min: int = 0


class TripOut(BaseModel):
    trip_no: int
    start_min: int
    end_min: int
    km: float
    kg: int
    capacity_pct: float
    geometry: list[list[float]]
    stops: list[StopOut]


class VehiclePlanOut(BaseModel):
    vehicle_id: str
    capacity_kg: int
    trips: list[TripOut]


class UnservedOut(BaseModel):
    order_id: str
    client_code: str
    client_name: str
    kg: int
    reason: str
    reason_label: str


class BaselineOut(BaseModel):
    cost_mxn: float
    served_kg: int


class ComparisonOut(BaseModel):
    served_kg_diff: int
    cost_diff_mxn: float
    optimized_is_better_or_equal: bool


class PlanOut(BaseModel):
    shift_start: str = "09:00"
    summary: PlanSummary
    uses_unverified_locations: bool
    unverified_clients: list[str]
    afternoon_load: list[AfternoonLoad]
    vehicles: list[VehiclePlanOut]
    unserved: list[UnservedOut]
    baseline: BaselineOut
    comparison: ComparisonOut
    lock_cost_diff_mxn: float | None


class PlanStatusOut(BaseModel):
    status: str
    stale: bool
    error: str | None
    plan: PlanOut | None
    computed_at: str | None


def _pct(kg: int, capacity_kg: int) -> float:
    return round(100 * kg / capacity_kg, 1)


def _trip_geometry(problem: Problem, trip: Trip, geometry: GeometryFn | None) -> list[list[float]]:
    """Un fallo de geometría deja el viaje sin trazo, pero nunca invalida el plan."""
    if geometry is None:
        return []
    stops = [problem.clients[s.client_code].location for s in trip.stops]
    try:
        return geometry([problem.depot, *stops, problem.depot])
    except Exception as e:
        logger.warning("sin geometría para un viaje: %s", e)
        return []


def plan_out(
    problem: Problem,
    plan: Plan,
    baseline: Plan,
    comparison: Comparison,
    lock_cost_diff: float | None,
    geometry: GeometryFn | None = None,
) -> PlanOut:
    capacities = {v.vehicle_id: v.capacity_kg for v in problem.vehicles}
    names = {code: c.name for code, c in problem.clients.items()}
    orders = {o.order_id: o for o in merge_orders(problem.orders)}

    vehicles = []
    for vp in plan.vehicles:
        capacity = capacities[vp.vehicle_id]
        vehicles.append(VehiclePlanOut(
            vehicle_id=vp.vehicle_id,
            capacity_kg=capacity,
            trips=[
                TripOut(
                    trip_no=t.trip_no, start_min=t.start_min, end_min=t.end_min, km=t.km, kg=t.kg,
                    capacity_pct=_pct(t.kg, capacity),
                    geometry=_trip_geometry(problem, t, geometry),
                    stops=[
                        StopOut(
                            order_id=s.order_id, client_code=s.client_code,
                            client_name=names[s.client_code], kg=s.kg,
                            arrival_min=s.arrival_min, departure_min=s.departure_min,
                            ordered_kg=orders[s.order_id].kg, wait_min=s.wait_min, window_start=s.window_start,
                            window_end=s.window_end, late_min=s.late_min,
                        )
                        for s in t.stops
                    ],
                )
                for t in vp.trips
            ],
        ))

    unserved = []
    for u in plan.unserved:
        order = orders[u.order_id]
        unserved.append(UnservedOut(
            order_id=u.order_id, client_code=order.client_code,
            client_name=names[order.client_code], kg=order.kg if u.kg is None else u.kg,
            reason=u.reason.value, reason_label=REASONS_ES[u.reason.value],
        ))

    unverified = sorted({
        o.client_code for o in problem.orders
        if problem.clients[o.client_code].location_status != LocationStatus.VERIFICADA
    })
    return PlanOut(
        summary=PlanSummary(
            cost_mxn=plan.cost_mxn, km_total=plan.km_total, liters_total=plan.liters_total,
            reloads=plan.reloads, vehicles_used=len(plan.vehicles), served_kg=served_kg(plan),
            unserved_kg=sum(u.kg for u in unserved),
            late_stops=sum(s.late_min > 0 for vp in plan.vehicles for t in vp.trips for s in t.stops),
            puesta_stops=sum(
                s.kg < orders[s.order_id].kg for vp in plan.vehicles for t in vp.trips for s in t.stops
            ),
        ),
        uses_unverified_locations=bool(unverified),
        unverified_clients=unverified,
        afternoon_load=[
            AfternoonLoad(
                vehicle_id=v.vehicle_id, kg=v.trips[0].kg, orders=len(v.trips[0].stops),
                capacity_pct=v.trips[0].capacity_pct,
            )
            for v in vehicles
        ],
        vehicles=vehicles,
        unserved=unserved,
        baseline=BaselineOut(cost_mxn=baseline.cost_mxn, served_kg=served_kg(baseline)),
        comparison=ComparisonOut(
            served_kg_diff=comparison.served_kg_diff,
            cost_diff_mxn=comparison.cost_diff_mxn,
            optimized_is_better_or_equal=comparison.optimized_is_better_or_equal,
        ),
        lock_cost_diff_mxn=lock_cost_diff,
    )
