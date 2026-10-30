from __future__ import annotations

from hcvrp.domain import (
    LocationStatus, Order, Params, Plan, Problem, Stop, Trip, Unserved, VehiclePlan,
)

DEPOT_KEY = "DEPOT"


def build_trip(trip_no: int, start_min: int, orders: list[Order], matrix, params: Params) -> Trip:
    prev, t, km = DEPOT_KEY, start_min, 0.0
    stops: list[Stop] = []
    for o in orders:
        arrival = t + matrix.minutes(prev, o.client_code)
        t = arrival + params.service_minutes
        km += matrix.km(prev, o.client_code)
        stops.append(Stop(o.order_id, o.client_code, o.kg, arrival, t))
        prev = o.client_code
    end = t + matrix.minutes(prev, DEPOT_KEY)
    km += matrix.km(prev, DEPOT_KEY)
    return Trip(trip_no, start_min, end, km, tuple(stops))


def build_vehicle_plan(vehicle_id: str, trips: list[list[Order]], matrix, params: Params) -> VehiclePlan:
    built: list[Trip] = []
    start = 0
    for orders in trips:
        if not orders:
            continue
        trip = build_trip(len(built) + 1, start, orders, matrix, params)
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
