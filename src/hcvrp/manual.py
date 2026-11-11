"""Ajustes a mano (pedidos fijados y orden de paradas): por qué uno no se puede cumplir, y el
plan vigente con el ajuste aplicado para no revolver lo que no se tocó."""
from __future__ import annotations

from hcvrp.domain import SHIFT_START_MIN, Order, Problem, minutes_to_clock
from hcvrp.precheck import merge_orders
from hcvrp.schedule import build_vehicle_plan, service_bounds

Routes = dict[str, list[list[str]]]  # camión -> viajes -> pedidos en orden


def _clock(minute: int) -> str:
    return minutes_to_clock(SHIFT_START_MIN + minute)


def _kg(value: int) -> str:
    return f"{value:,} kg"


def manual_violations(problem: Problem, matrix=None) -> list[str]:
    """Reglas que lo fijado a mano rompe por sí solo, sin importar qué más decida el plan.

    Capacidad de cada viaje fijado y, con `matrix`, jornada y horario de los clientes en los
    camiones con orden a mano (agregarles más paradas solo los retrasaría). Lista vacía: nada
    que objetar todavía.
    """
    out: list[str] = []
    fleet = {v.vehicle_id: v for v in problem.vehicles}
    orders = {o.order_id: o for o in merge_orders(problem.orders)}
    name = lambda o: problem.clients[o.client_code].name  # noqa: E731
    trips: dict[str, dict[int, list[Order]]] = {}
    for order_id, (vehicle_id, trip_no) in problem.locks.items():
        order, truck = orders.get(order_id), fleet.get(vehicle_id)
        if order is None or truck is None:
            continue
        if trip_no is None:
            if order.kg > truck.capacity_kg:
                out.append(
                    f"el pedido de {name(order)} ({_kg(order.kg)}) no cabe en {vehicle_id}, "
                    f"que carga {_kg(truck.capacity_kg)}"
                )
            continue
        trips.setdefault(vehicle_id, {}).setdefault(trip_no, []).append(order)

    for vehicle_id, by_trip in trips.items():
        truck = fleet[vehicle_id]
        for trip_no, items in sorted(by_trip.items()):
            items.sort(key=lambda o: problem.positions.get(o.order_id, 10**9))
            kg = sum(o.kg for o in items)
            if kg > truck.capacity_kg:
                who = ", ".join(name(o) for o in items)
                out.append(
                    f"el viaje {trip_no} de {vehicle_id} llevaría {_kg(kg)} ({who}) y al camión le "
                    f"caben {_kg(truck.capacity_kg)}"
                )
        manual = any(o.order_id in problem.positions for items in by_trip.values() for o in items)
        located = all(problem.clients[o.client_code].location is not None for items in by_trip.values() for o in items)
        if matrix is None or not manual or not located:
            continue
        params = problem.params
        plan = build_vehicle_plan(
            vehicle_id, [by_trip[t] for t in sorted(by_trip)], matrix, params, problem.clients
        )
        for trip, trip_no in zip(plan.trips, sorted(by_trip)):
            for stop in trip.stops:
                client = problem.clients[stop.client_code]
                _, latest = service_bounds(orders[stop.order_id], client, params)
                if latest is not None and stop.arrival_min > latest:
                    out.append(
                        f"en el viaje {trip_no} de {vehicle_id}, la entrega a {client.name} terminaría a las "
                        f"{_clock(stop.departure_min)} y el cliente recibe hasta las {minutes_to_clock(client.closes_at)}"
                    )
            if trip.end_min > params.shift_minutes:
                out.append(
                    f"el viaje {trip_no} de {vehicle_id} regresaría a las {_clock(trip.end_min)}, "
                    f"después del fin de la jornada ({_clock(params.shift_minutes)})"
                )
    return out


def anchored_routes(previous: Routes, problem: Problem) -> Routes:
    """El plan anterior con lo fijado a mano aplicado y nada más movido.

    Quita pedidos que ya no existen, pasa cada pedido fijado a su camión (y viaje), y ordena
    por posición los viajes con orden a mano. No garantiza que el resultado sea válido.
    """
    alive = {o.order_id for o in merge_orders(problem.orders)}
    available = {v.vehicle_id for v in problem.vehicles if v.available}
    routes: Routes = {
        vid: [[oid for oid in trip if oid in alive] for trip in trips]
        for vid, trips in previous.items() if vid in available
    }
    for order_id, (vehicle_id, trip_no) in problem.locks.items():
        if order_id not in alive or vehicle_id not in available:
            continue
        here = routes.setdefault(vehicle_id, [])
        at = next((t for t, trip in enumerate(here, start=1) if order_id in trip), None)
        if at is not None and trip_no in (None, at) and order_id not in problem.positions:
            continue
        for trips in routes.values():
            for trip in trips:
                if order_id in trip:
                    trip.remove(order_id)
        target = trip_no or max(len(here), 1)
        while len(here) < target:
            here.append([])
        here[target - 1].append(order_id)
    for order_id in problem.positions:
        lock = problem.locks.get(order_id)
        if lock and lock[0] in routes and lock[1] and lock[1] <= len(routes[lock[0]]):
            trip = routes[lock[0]][lock[1] - 1]
            fixed = sorted((o for o in trip if o in problem.positions), key=problem.positions.get)
            it = iter(fixed)
            trip[:] = [next(it) if o in problem.positions else o for o in trip]
    return {vid: [t for t in trips if t] for vid, trips in routes.items() if any(trips)}
