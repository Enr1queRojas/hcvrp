from __future__ import annotations

from hcvrp.domain import Location, Order, Problem, Unserved, UnservedReason
from hcvrp.geo.matrix import Matrix


def merge_orders(orders: list[Order]) -> list[Order]:
    """Suma kg por cliente; conserva el primer order_id y el orden de primera aparición."""
    merged: dict[str, Order] = {}
    for o in orders:
        prev = merged.get(o.client_code)
        if prev is None:
            merged[o.client_code] = o
        else:
            merged[o.client_code] = Order(prev.order_id, prev.client_code, prev.kg + o.kg)
    return list(merged.values())


def points_for(problem: Problem) -> dict[str, Location]:
    """DEPOT + clientes de los pedidos que tienen ubicacion (para pedir la matriz)."""
    points: dict[str, Location] = {"DEPOT": problem.depot}
    for o in problem.orders:
        client = problem.clients.get(o.client_code)
        if client is not None and client.location is not None:
            points.setdefault(client.code, client.location)
    return points


def _check_locks(problem: Problem, merged: list[Order]) -> None:
    vehicles = {v.vehicle_id: v for v in problem.vehicles}
    surviving = {o.order_id for o in merged}
    survivor_by_original: dict[str, str] = {}
    first_by_client = {o.client_code: o.order_id for o in merged}
    for o in problem.orders:
        survivor_by_original[o.order_id] = first_by_client[o.client_code]
    max_trips = problem.params.max_trips_per_vehicle
    for order_id, (vehicle_id, trip_no) in problem.locks.items():
        if order_id not in surviving:
            if order_id in survivor_by_original:
                raise ValueError(
                    f"lock on order {order_id!r}: it was merged into order "
                    f"{survivor_by_original[order_id]!r}; lock that one instead"
                )
            raise ValueError(f"lock on unknown order {order_id!r}")
        vehicle = vehicles.get(vehicle_id)
        if vehicle is None:
            raise ValueError(f"lock on order {order_id!r}: unknown vehicle {vehicle_id!r}")
        if not vehicle.available:
            raise ValueError(f"lock on order {order_id!r}: vehicle {vehicle_id!r} is unavailable")
        if trip_no is not None and not 1 <= trip_no <= max_trips:
            raise ValueError(
                f"lock on order {order_id!r}: trip_no {trip_no} outside 1..{max_trips}"
            )
    for order_id in problem.positions:
        lock = problem.locks.get(order_id)
        if lock is None or lock[1] is None:
            raise ValueError(f"position on order {order_id!r} without a (vehicle, trip) lock")


def precheck(problem: Problem, matrix: Matrix) -> tuple[list[Order], list[Unserved]]:
    """Separa los pedidos fusionados en (planeables, no servidos por inviables)."""
    merged = merge_orders(problem.orders)
    for o in merged:
        if o.client_code not in problem.clients:
            raise ValueError(f"unknown client code {o.client_code!r} in order {o.order_id!r}")
    _check_locks(problem, merged)

    caps = [v.capacity_kg for v in problem.vehicles if v.available]
    max_cap = max(caps) if caps else None  # sin flota: lo reporta el solver (saturacion)
    params = problem.params
    planeable: list[Order] = []
    unserved: list[Unserved] = []
    for o in merged:
        client = problem.clients[o.client_code]
        if client.location is None:
            reason = UnservedReason.SIN_COORDENADAS
        elif max_cap is not None and o.kg > max_cap:
            reason = UnservedReason.EXCEDE_CAPACIDAD
        elif (
            matrix.minutes("DEPOT", client.code)
            + params.service_minutes
            + matrix.minutes(client.code, "DEPOT")
            > params.shift_minutes
        ):
            reason = UnservedReason.NO_CABE_JORNADA
        else:
            planeable.append(o)
            continue
        unserved.append(Unserved(o.order_id, reason))
    for u in unserved:
        if u.order_id in problem.locks:
            vehicle_id, trip_no = problem.locks[u.order_id]
            where = f"el camión {vehicle_id!r}" + (f", viaje {trip_no}" if trip_no else "")
            raise ValueError(
                f"bloqueo imposible: el pedido {u.order_id!r} no se puede servir "
                f"({u.reason.value}) y está bloqueado en {where}"
            )
    return planeable, unserved
