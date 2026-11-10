from __future__ import annotations

from hcvrp.domain import (
    SHIFT_START_MIN, Client, LocationStatus, Order, Params, Plan, Problem, Stop, Trip, Unserved,
    VehiclePlan,
)

DEPOT_KEY = "DEPOT"


def service_bounds(
    order: Order, client: Client | None, params: Params, kg: int | None = None
) -> tuple[int, int | None]:
    """(inicio más temprano, inicio más tardío) de la entrega, en minutos de jornada.

    Combina el "desde" del pedido con el horario del cliente; ambos son firmes. El inicio más
    tardío deja tiempo para terminar de descargar antes de que cierre: depende de los kilos que
    se entregan (`kg`; por omisión, el pedido completo). None: sin límite.
    """
    earliest = order.window_start or 0
    latest = None
    if client is not None:
        earliest = max(earliest, client.opens_at - SHIFT_START_MIN)
        delivered = order.kg if kg is None else kg
        latest = client.closes_at - SHIFT_START_MIN - params.service_time(delivered)
    return earliest, latest


def build_trip(
    trip_no: int,
    start_min: int,
    orders: list[Order],
    matrix,
    params: Params,
    clients: dict[str, Client] | None = None,
) -> Trip:
    prev, t, km = DEPOT_KEY, start_min, 0.0
    stops: list[Stop] = []
    for o in orders:
        reached = t + matrix.minutes(prev, o.client_code)
        earliest, _ = service_bounds(o, (clients or {}).get(o.client_code), params)
        arrival = max(reached, earliest)  # si llega antes de que se pueda entregar, espera
        t = arrival + params.service_time(o.kg)
        km += matrix.km(prev, o.client_code)
        stops.append(Stop(
            o.order_id, o.client_code, o.kg, arrival, t,
            wait_min=arrival - reached, window_start=o.window_start, window_end=o.window_end,
        ))
        prev = o.client_code
    end = t + matrix.minutes(prev, DEPOT_KEY)
    km += matrix.km(prev, DEPOT_KEY)
    return Trip(trip_no, start_min, end, km, tuple(stops))


def build_vehicle_plan(
    vehicle_id: str,
    trips: list[list[Order]],
    matrix,
    params: Params,
    clients: dict[str, Client] | None = None,
) -> VehiclePlan:
    built: list[Trip] = []
    start = 0
    for orders in trips:
        if not orders:
            continue
        trip = build_trip(len(built) + 1, start, orders, matrix, params, clients)
        built.append(trip)
        start = trip.end_min + params.reload_minutes
    return VehiclePlan(vehicle_id, tuple(built))


def summarize(problem: Problem, vehicle_plans: list[VehiclePlan], unserved: list[Unserved], matrix) -> Plan:
    fleet = {v.vehicle_id: v for v in problem.vehicles}
    used = [vp for vp in vehicle_plans if vp.trips]
    cost = km_total = liters = 0.0
    total_trips = 0
    unverified = False
    for vp in used:
        v = fleet[vp.vehicle_id]
        cost += v.fixed_dispatch_cost_mxn
        for trip in vp.trips:
            total_trips += 1
            l = trip.km / v.km_per_liter
            liters += l
            km_total += trip.km
            cost += l * problem.params.diesel_mxn_per_liter + trip.kg * problem.params.loading_mxn_per_kg
            for s in trip.stops:
                if problem.clients[s.client_code].location_status != LocationStatus.VERIFICADA:
                    unverified = True
    return Plan(tuple(used), tuple(unserved), cost, km_total, liters, total_trips - len(used), unverified)
