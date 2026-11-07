from __future__ import annotations

from hcvrp.domain import Plan, Problem, puesta_amounts
from hcvrp.precheck import merge_orders
from hcvrp.schedule import service_bounds

DEPOT_KEY = "DEPOT"
TOL = 0.01


def validate(problem: Problem, plan: Plan, matrix) -> list[str]:
    """Valida un plan de forma independiente (re-derivado desde la matriz).

    Devuelve la lista de violaciones en español; vacía significa plan válido.
    """
    out: list[str] = []
    params = problem.params
    fleet = {v.vehicle_id: v for v in problem.vehicles}
    orders = {o.order_id: o for o in merge_orders(problem.orders)}

    seen: dict[str, int] = {}
    served_kg: dict[str, int] = {}
    placement: dict[str, tuple[str, int]] = {}
    cost = km_total = liters = 0.0
    total_trips = used = 0
    vehicle_ids_seen: set[str] = set()

    for vp in plan.vehicles:
        vid = vp.vehicle_id
        if vid in vehicle_ids_seen:
            out.append(f"Camión {vid}: aparece más de una vez en el plan")
        vehicle_ids_seen.add(vid)
        veh = fleet.get(vid)
        if veh is None:
            out.append(f"Camión {vid}: no existe en la flota")
            continue
        if not veh.available:
            out.append(f"Camión {vid}: no disponible pero tiene viajes asignados")
        if len(vp.trips) > params.max_trips_per_vehicle:
            out.append(
                f"Camión {vid}: {len(vp.trips)} viajes exceden el máximo de {params.max_trips_per_vehicle}"
            )
        if vp.trips:
            used += 1
            cost += veh.fixed_dispatch_cost_mxn

        prev_end: int | None = None
        for idx, trip in enumerate(vp.trips, start=1):
            tag = f"Camión {vid} viaje {trip.trip_no}"
            total_trips += 1
            if trip.trip_no != idx:
                out.append(f"{tag}: numeración de viaje incorrecta (se esperaba {idx})")
            expected_start = 0 if prev_end is None else prev_end + params.reload_minutes
            if trip.start_min != expected_start:
                if prev_end is None:
                    out.append(f"{tag}: el primer viaje debe iniciar en el minuto 0, inicia en {trip.start_min}")
                else:
                    out.append(
                        f"{tag}: recarga incorrecta, inicia en {trip.start_min} y debe iniciar en "
                        f"{expected_start} (fin anterior {prev_end} + {params.reload_minutes} min de recarga)"
                    )

            # Re-derivar horarios y km desde la matriz.
            try:
                prev, t, km = DEPOT_KEY, trip.start_min, 0.0
                for s in trip.stops:
                    o = orders.get(s.order_id)
                    reached = t + matrix.minutes(prev, s.client_code)
                    earliest, latest = (
                        service_bounds(o, problem.clients.get(s.client_code), params) if o else (0, None)
                    )
                    arrival = max(reached, earliest)
                    dep = arrival + params.service_minutes
                    if latest is not None and arrival > latest:
                        out.append(
                            f"{tag}: la parada {s.order_id} se entrega fuera del horario del cliente "
                            f"(empieza en el minuto {arrival}, a más tardar {latest})"
                        )
                    if s.wait_min != arrival - reached:
                        out.append(
                            f"{tag}: espera de la parada {s.order_id} no coincide "
                            f"({s.wait_min}/{arrival - reached} min)"
                        )
                    km += matrix.km(prev, s.client_code)
                    if s.arrival_min != arrival or s.departure_min != dep:
                        out.append(
                            f"{tag}: horario de parada {s.order_id} no coincide con la matriz "
                            f"(llegada {s.arrival_min}/{arrival}, salida {s.departure_min}/{dep})"
                        )
                    t, prev = dep, s.client_code
                end = t + matrix.minutes(prev, DEPOT_KEY)
                km += matrix.km(prev, DEPOT_KEY)
            except (KeyError, TypeError):
                out.append(f"{tag}: cliente sin datos en la matriz ({prev} -> {s.client_code})")
                km = trip.km
                end = trip.end_min
            else:
                if trip.end_min != end:
                    out.append(f"{tag}: horario de fin {trip.end_min} no coincide con la matriz ({end})")
                if abs(trip.km - km) > TOL:
                    out.append(f"{tag}: km {trip.km:.2f} no coincide con la matriz ({km:.2f})")
            if end > params.shift_minutes or trip.end_min > params.shift_minutes:
                out.append(
                    f"{tag}: regresa a bodega en el minuto {max(end, trip.end_min)}, "
                    f"después del límite de jornada de {params.shift_minutes}"
                )
            prev_end = trip.end_min

            if trip.kg > veh.capacity_kg:
                out.append(f"{tag}: kg {trip.kg} exceden la capacidad de {veh.capacity_kg} kg")

            for s in trip.stops:
                client = problem.clients.get(s.client_code)
                if client is not None and not client.can_receive(vid):
                    out.append(f"{tag}: el camión {vid} no puede entrar con el cliente {s.client_code}")
                seen[s.order_id] = seen.get(s.order_id, 0) + 1
                placement[s.order_id] = (vid, trip.trip_no)
                o = orders.get(s.order_id)
                if o is None:
                    out.append(f"{tag}: pedido {s.order_id} no existe en el problema")
                    continue
                served_kg[s.order_id] = s.kg
                if s.kg != o.kg:
                    client = problem.clients.get(o.client_code)
                    is_puesta = (
                        client is not None and client.puesta and s.order_id not in problem.locks
                        and s.kg in puesta_amounts(o.kg)
                    )
                    if not is_puesta:
                        out.append(f"{tag}: pedido {s.order_id} entrega {s.kg} kg pero el pedido es de {o.kg} kg")
                if s.client_code != o.client_code:
                    out.append(f"{tag}: pedido {s.order_id} atendido en cliente {s.client_code}, corresponde a {o.client_code}")

            if veh.km_per_liter > 0:
                l = km / veh.km_per_liter
                liters += l
                cost += l * params.diesel_mxn_per_liter + trip.kg * params.loading_mxn_per_kg
            km_total += km

    left_kg: dict[str, int] = {}
    for u in plan.unserved:
        if u.order_id not in orders:
            out.append(f"Pedido {u.order_id}: no servido pero no existe en el problema")
        if u.kg is not None:  # lo que faltó de una puesta: el pedido ya cuenta como servido
            left_kg[u.order_id] = left_kg.get(u.order_id, 0) + u.kg
            continue
        seen[u.order_id] = seen.get(u.order_id, 0) + 1

    for oid, o in orders.items():
        got, left = served_kg.get(oid), left_kg.get(oid, 0)
        if got is not None and got + left != o.kg:
            out.append(f"Pedido {oid}: se entregan {got} kg y faltan {left} kg, pero el pedido es de {o.kg} kg")
        if got is None and left:
            out.append(f"Pedido {oid}: tiene kilos pendientes de puesta pero no se entregó nada")

    for oid in orders:
        n = seen.get(oid, 0)
        if n == 0:
            out.append(f"Pedido {oid}: falta, no está servido ni en no servidos")
        elif n > 1:
            out.append(f"Pedido {oid}: aparece {n} veces en el plan")

    for oid, (lv, lt) in problem.locks.items():
        got = placement.get(oid)
        if lt is None:
            if got is None or got[0] != lv:
                out.append(f"Pedido {oid}: bloqueo no respetado, debía ir en {lv}, quedó en {got}")
        elif got != (lv, lt):
            out.append(f"Pedido {oid}: bloqueo no respetado, debía ir en {lv} viaje {lt}, quedó en {got}")

    sequence = {
        s.order_id: (vp.vehicle_id, trip.trip_no, i)
        for vp in plan.vehicles for trip in vp.trips for i, s in enumerate(trip.stops)
    }
    by_trip: dict[tuple[str, int], list[tuple[int, str]]] = {}
    for oid, pos in problem.positions.items():
        if oid in sequence and problem.locks.get(oid) and problem.locks[oid][1] is not None:
            by_trip.setdefault(problem.locks[oid], []).append((pos, oid))
    for (lv, lt), items in by_trip.items():
        wanted = [oid for _, oid in sorted(items)]
        got = sorted(wanted, key=lambda oid: sequence[oid][2])
        if got != wanted:
            out.append(f"{lv} viaje {lt}: orden a mano no respetado, debía ser {wanted}, quedó {got}")

    reloads = total_trips - used
    if abs(plan.cost_mxn - cost) > TOL:
        out.append(f"Plan: costo {plan.cost_mxn:.2f} no coincide con el recalculado {cost:.2f}")
    if abs(plan.liters_total - liters) > TOL:
        out.append(f"Plan: litros {plan.liters_total:.2f} no coinciden con los recalculados {liters:.2f}")
    if abs(plan.km_total - km_total) > TOL:
        out.append(f"Plan: km totales {plan.km_total:.2f} no coinciden con los recalculados {km_total:.2f}")
    if plan.reloads != reloads:
        out.append(f"Plan: recargas {plan.reloads} no coinciden con las recalculadas {reloads}")
    return out
