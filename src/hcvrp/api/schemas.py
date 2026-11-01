"""Modelos de entrada y salida de la API."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date as Date
from typing import Annotated, Any

from pydantic import (
    BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, model_validator,
)

from hcvrp.baseline import Comparison, served_kg
from hcvrp.cli import REASONS_ES
from hcvrp.domain import Client, Location, LocationStatus, Plan, Problem

LAGUNA_BOUNDS = (25.30, 25.80, -103.80, -103.10)  # (lat_min, lat_max, lon_min, lon_max)
MAX_ORDER_KG = 1_000_000

GeometryFn = Callable[[list[Location]], list[list[float]]]

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


def _check_kg(value: Any) -> int:
    if type(value) is not int or not 1 <= value <= MAX_ORDER_KG:
        raise ValueError(f"los kg deben ser un número entero entre 1 y {MAX_ORDER_KG}")
    return value


Kg = Annotated[int, BeforeValidator(_check_kg)]


class OrderIn(BaseModel):
    date: Date
    client_code: str
    kg: Kg


class OrderPatch(BaseModel):
    kg: Kg


class LockIO(BaseModel):
    vehicle_id: str
    trip_no: int = Field(ge=1)


class OrderOut(BaseModel):
    id: int
    date: Date
    client_code: str
    client_name: str
    kg: int
    lock: LockIO | None


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


def _pct(kg: int, capacity_kg: int) -> float:
    return round(100 * kg / capacity_kg, 1)


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
    orders = {o.order_id: o for o in problem.orders}

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
                    geometry=[],
                    stops=[
                        StopOut(
                            order_id=s.order_id, client_code=s.client_code,
                            client_name=names[s.client_code], kg=s.kg,
                            arrival_min=s.arrival_min, departure_min=s.departure_min,
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
            client_name=names[order.client_code], kg=order.kg,
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
