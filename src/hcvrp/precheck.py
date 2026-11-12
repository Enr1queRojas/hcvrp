from __future__ import annotations

from hcvrp.domain import (
    Client, Location, Order, Params, Problem, Unserved, UnservedReason, puesta_amounts,
)
from hcvrp.geo.matrix import Matrix
from hcvrp.schedule import service_bounds


def _merge_window(a: Order, b: Order) -> tuple[int | None, int | None]:
    """Horario común de dos pedidos del mismo cliente; si no se traslapan, gana el primero."""
    starts = [w for w in (a.window_start, b.window_start) if w is not None]
    ends = [w for w in (a.window_end, b.window_end) if w is not None]
    start = max(starts) if starts else None
    end = min(ends) if ends else None
    if start is not None and end is not None and start >= end:
        return a.window_start, a.window_end
    return start, end


def merge_orders(orders: list[Order]) -> list[Order]:
    """Suma kg por cliente; conserva el primer order_id y el orden de primera aparición."""
    merged: dict[str, Order] = {}
    for o in orders:
        prev = merged.get(o.client_code)
        if prev is None:
            merged[o.client_code] = o
        else:
            start, end = _merge_window(prev, o)
            merged[o.client_code] = Order(prev.order_id, prev.client_code, prev.kg + o.kg, start, end)
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
    client_of = {o.order_id: o.client_code for o in merged}
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
        client = problem.clients.get(client_of.get(order_id, ""))
        if client is not None and not client.can_receive(vehicle_id):
            raise ValueError(
                f"bloqueo imposible: el camión {vehicle_id!r} no puede entrar con el cliente "
                f"{client.code!r} y el pedido {order_id!r} está bloqueado en él"
            )
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


def alone_reason(
    order: Order, client: Client, params: Params, matrix: Matrix, kg: int | None = None
) -> UnservedReason | None:
    """Por qué no cabe una entrega de `kg` (por omisión, el pedido completo) ni yendo directo
    desde la bodega; None si cabe. La descarga dura según los kilos, así que un pedido grande
    puede no caber en el horario del cliente o en la jornada aunque su puesta sí."""
    delivered = order.kg if kg is None else kg
    earliest, latest = service_bounds(order, client, params, delivered)
    start = max(matrix.minutes("DEPOT", client.code), earliest)
    if latest is not None and start > latest:
        return UnservedReason.FUERA_HORARIO_CLIENTE
    if start + params.service_time(delivered) + matrix.minutes(client.code, "DEPOT") > params.shift_minutes:
        return UnservedReason.NO_CABE_JORNADA
    return None


def _deliverable_sizes(problem: Problem, order: Order, client: Client, fits: list[int]) -> list[int]:
    """Kilos que se le pueden llevar en una visita, de mayor a menor: el pedido completo y, si el
    cliente tiene puesta y el pedido no está fijado, sus partes. Solo los que caben en algún
    camión que puede entrar (sin camiones disponibles no hay contra qué comparar)."""
    sizes = [order.kg]
    if client.puesta and order.order_id not in problem.locks:
        sizes += puesta_amounts(order.kg)
    return [kg for kg in sizes if not fits or kg <= max(fits)]


def precheck(problem: Problem, matrix: Matrix) -> tuple[list[Order], list[Unserved]]:
    """Separa los pedidos fusionados en (planeables, no servidos por inviables)."""
    merged = merge_orders(problem.orders)
    for o in merged:
        if o.client_code not in problem.clients:
            raise ValueError(f"unknown client code {o.client_code!r} in order {o.order_id!r}")
    _check_locks(problem, merged)

    available = [v for v in problem.vehicles if v.available]
    params = problem.params
    planeable: list[Order] = []
    unserved: list[Unserved] = []
    for o in merged:
        client = problem.clients[o.client_code]
        fits = [v.capacity_kg for v in available if client.can_receive(v.vehicle_id)]
        if client.location is None:
            reason = UnservedReason.SIN_COORDENADAS
        elif available and not fits:
            reason = UnservedReason.NINGUN_CAMION_ENTRA
        elif not (sizes := _deliverable_sizes(problem, o, client, fits)):
            reason = UnservedReason.EXCEDE_CAPACIDAD
        else:
            # Basta con que quepa alguna forma de entregarlo; si ninguna, el motivo es el de la
            # más grande (el pedido completo, o su mayor puesta si excede a los camiones).
            reasons = [alone_reason(o, client, params, matrix, kg) for kg in sizes]
            if None in reasons:
                planeable.append(o)
                continue
            reason = reasons[0]
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
