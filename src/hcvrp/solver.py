"""Solver multi-viaje con OR-Tools.

Formulación (equivalente a las copias (k, t) del plan; ver reporte de la Tarea 7):
cada camión disponible k es UN vehículo de OR-Tools cuya ruta encadena sus viajes.
Por camión hay `max_trips_per_vehicle - 1` nodos opcionales de *recarga* (copias de la
bodega, solo visitables por k) con servicio = `reload_minutes`. Al pasar por uno:

* la dimensión de tiempo suma la recarga, así que el viaje t+1 empieza en
  fin(t) + recarga y todo cabe en `shift_minutes` (el viaje 1 arranca en 0);
* la dimensión de capacidad tiene demanda -capacidad(k) con holgura [0, capacidad(k)],
  lo que deja la carga en 0 para el siguiente viaje;
* la dimensión "Trips" cuenta viajes (sirve para los bloqueos (camión, viaje)).

Bloqueos: (camión, viaje) fija ambos; (camión, None) solo el camión. El orden a mano
(`problem.positions`) usa una dimensión "Rank" que cuenta paradas: entre los pedidos con
posición del mismo (camión, viaje), el rango debe crecer en el orden dado. Otros pedidos
pueden quedar intercalados.

Descarga: cada entrega dura `Params.service_time(kg)` (fijo por parada + minutos por tonelada),
así que pesa en la jornada y en el horario del cliente según los kilos que se bajan.

Horarios de entrega (`Order.window_start/window_end`) y de recepción del cliente
(`Client.opens_at/closes_at`): solo si algún "no antes de" obliga a esperar, la dimensión de
tiempo admite espera (holgura). El horario del cliente y `window_start` son firmes (el camión
espera; nunca se agenda fuera de lo que el cliente recibe: la descarga termina antes del cierre);
`window_end` es blando: cada minuto tarde cuesta LATE_PENALTY_PER_MIN, y la penalización por
descartar un pedido supera cualquier retraso posible, así que nunca se dejan kilos por cumplir
un horario.

Puesta (`Client.puesta`) es el último recurso antes de mandar un pedido a otro día, en dos
pasos: primero el plan normal; si quedaron fuera pedidos libres (no bloqueados) de clientes con
puesta, un segundo paso parte de ese plan y agrega, solo para ellos, nodos alternativos con una
parte de los kilos (`puesta_amounts`; a lo más uno por pedido). Los kilos que la puesta deja sin
entregar cuestan DROP_PENALTY_PER_KG cada uno (cargado en los arcos que salen del nodo), así que
siempre conviene más que no entregar nada. Como el segundo paso arranca de la solución del primero
y solo acepta mejoras, nunca entrega menos kilos que el plan sin puesta. (Dar alternativas a
todos los pedidos desde el principio triplicaba los nodos y la búsqueda encontraba planes peores.)

Por construcción los viajes se usan en orden (t usado => t-1 usado) y no hay viajes
vacíos intermedios (sin recarga justo al salir ni dos recargas seguidas); un viaje final
vacío (recarga justo antes de cerrar) se descarta al armar el plan.
Con copias por vehículo y restricciones de CP entre sus cumuls, la búsqueda local de
OR-Tools 9.15 rechazaba todo movimiento (descartaba todos los pedidos).

El horario final lo recalcula `schedule.build_vehicle_plan` (cada camión sale en cuanto puede
y espera en la puerta del cliente si llega antes), que nunca es más tardío que el del solver.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from hcvrp.domain import Order, Plan, Problem, Unserved, UnservedReason, Vehicle, puesta_amounts
from hcvrp.geo.matrix import DistanceProvider, Matrix
from hcvrp.precheck import alone_reason, points_for, precheck
from hcvrp.schedule import DEPOT_KEY, build_vehicle_plan, service_bounds, summarize
from hcvrp.validate import validate

DROP_PENALTY_PER_KG = 100_000  # centavos por kg (1 000 MXN/kg)
LATE_PENALTY_PER_MIN = 50_000  # centavos por minuto tarde (500 MXN/min): pesa más que un rodeo
WAIT_COST_PER_MIN = 300  # centavos por minuto de espera (3 MXN/min): usar el hueco para otras entregas
EXTRA_TRIP_COST = 10  # centavos por recarga; desempate: menos recargas

# La búsqueda no agota `time_limit_s` si lleva un rato sin mejorar: al menos STALL_S segundos, y
# más si el último avance llegó tarde (STALL_RATIO veces lo que tardó en llegar). Cuando todo se
# entrega solo quedan pesos de ruta por ganar y se corta pronto; mientras queden kilos fuera se
# insiste más, porque cada kilo pesa más que cualquier ruta. Medido en 28 días de prueba: con todo
# entregado se pierden en promedio 27 MXN por día frente a esperar siempre los 15 s.
STALL_S = 1.5
STALL_WITH_KILOS_OUT_S = 5.0
STALL_RATIO = 1.0


class SearchCancelled(Exception):
    """Quien pidió el plan ya no lo quiere (p. ej. sus datos cambiaron mientras se calculaba)."""


@dataclass(frozen=True)
class SearchStats:
    seconds: float  # lo que duró la búsqueda
    best_at_s: float  # cuándo apareció el plan que se devolvió
    improvements: int
    stopped_by: str  # "sin_mejora", "limite" (se acabó time_limit_s) o "fin" (no había más que buscar)


@dataclass
class SearchControl:
    """Permite cancelar la búsqueda desde fuera, pedirla a fondo y saber cómo le fue.

    `thorough`: usa todo `time_limit_s` aunque deje de mejorar (para cuando el plan ya es el
    que se va a ejecutar y vale la pena esperar)."""

    should_stop: Callable[[], bool] = lambda: False
    thorough: bool = False
    passes: list[SearchStats] = field(default_factory=list)


def solve(
    problem: Problem, provider: DistanceProvider, control: SearchControl | None = None
) -> tuple[Plan, Matrix]:
    control = control or SearchControl()
    matrix = provider.matrix(points_for(problem))
    planeable, unserved = precheck(problem, matrix)
    trucks = [v for v in problem.vehicles if v.available]

    if not planeable:
        routes: dict[str, list[list[Order]]] = {}
    elif not trucks:
        routes = {}
        unserved = unserved + [Unserved(o.order_id, UnservedReason.SATURACION_FLOTA) for o in planeable]
    else:
        routes, dropped, short = _route(problem, matrix, planeable, trucks, control)
        puesta_ids = {
            o.order_id for o in dropped
            if o.order_id not in problem.locks
            and (c := problem.clients.get(o.client_code)) is not None and c.puesta
        }
        if puesta_ids:  # último recurso: puesta solo para lo que se iba a otro día
            start = {vid: [[o.order_id for o in t] for t in trips if t] for vid, trips in routes.items()}
            routes, dropped, short = _route(problem, matrix, planeable, trucks, control, puesta_ids, start)
        _check_locks_honored(problem, planeable, routes)
        unserved = unserved + [
            Unserved(o.order_id, _drop_reason(problem, o, trucks, matrix)) for o in dropped
        ]
        unserved += [Unserved(oid, UnservedReason.PUESTA_PARCIAL, kg) for oid, kg in short.items()]

    vehicle_plans = [
        build_vehicle_plan(vid, trips, matrix, problem.params, problem.clients)
        for vid, trips in routes.items()
    ]
    plan = summarize(problem, vehicle_plans, unserved, matrix)
    violations = validate(problem, plan, matrix)
    if violations:
        raise AssertionError("plan inválido:\n" + "\n".join(violations))
    return plan, matrix


def _drop_reason(
    problem: Problem, order: Order, trucks: list[Vehicle], matrix: Matrix
) -> UnservedReason:
    """Un pedido que solo era planeable por su puesta (excede a los camiones, o su descarga
    completa no cabe en el horario o la jornada) llega aquí si ni la puesta cupo: el motivo es
    el del pedido completo. Lo demás que queda fuera es saturación."""
    client = problem.clients[order.client_code]
    fits = [t.capacity_kg for t in trucks if client.can_receive(t.vehicle_id)]
    if fits and order.kg > max(fits):
        return UnservedReason.EXCEDE_CAPACIDAD
    return alone_reason(order, client, problem.params, matrix) or UnservedReason.SATURACION_FLOTA


def _check_locks_honored(
    problem: Problem, planeable: list[Order], routes: dict[str, list[list[Order]]]
) -> None:
    planeable_ids = {o.order_id for o in planeable}
    for order_id, (vehicle_id, trip_no) in problem.locks.items():
        if order_id not in planeable_ids:
            continue
        trips = [t for t in routes.get(vehicle_id, []) if t]
        if trip_no is None:
            ok = any(o.order_id == order_id for t in trips for o in t)
        else:
            ok = trip_no <= len(trips) and any(o.order_id == order_id for o in trips[trip_no - 1])
        if not ok:
            where = f"el camión {vehicle_id!r}" + (f", viaje {trip_no}" if trip_no else "")
            raise ValueError(
                f"bloqueo infeasible: el pedido {order_id!r} no pudo servirse en "
                f"{where} (capacidad, jornada o viajes insuficientes)"
            )
    for vehicle_id, trip_no, wanted in _sequences(problem, planeable_ids):
        trip = [t for t in routes.get(vehicle_id, []) if t][trip_no - 1]
        got = [o.order_id for o in trip if o.order_id in set(wanted)]
        if got != wanted:
            raise ValueError(
                f"bloqueo infeasible: el orden fijado a mano en el camión {vehicle_id!r}, "
                f"viaje {trip_no} no se pudo respetar"
            )


def _sequences(problem: Problem, order_ids: set[str]) -> list[tuple[str, int, list[str]]]:
    """(camión, viaje, pedidos en el orden fijado) para cada viaje con orden a mano."""
    groups: dict[tuple[str, int], list[tuple[int, str]]] = {}
    for order_id, position in problem.positions.items():
        if order_id not in order_ids:
            continue
        vehicle_id, trip_no = problem.locks[order_id]
        groups.setdefault((vehicle_id, trip_no), []).append((position, order_id))
    return [(v, t, [oid for _, oid in sorted(items)]) for (v, t), items in groups.items() if len(items) > 1]


def _route(
    problem: Problem,
    matrix: Matrix,
    orders: list[Order],
    trucks: list[Vehicle],
    control: SearchControl,
    puesta_ids: set[str] = frozenset(),
    start: dict[str, list[list[str]]] | None = None,
) -> tuple[dict[str, list[list[Order]]], list[Order], dict[str, int]]:
    """Rutas por camión, pedidos sin entregar y {pedido: kg que faltaron} de las puestas.

    `puesta_ids`: pedidos que pueden llevarse en puesta. `start`: rutas de partida
    ({camión: [[pedidos del viaje]]}), p. ej. el plan del primer paso. Lanza `SearchCancelled`
    si `control.should_stop()` corta la búsqueda.

    Las tablas de costo, tiempo y kilos se registran dentro de OR-Tools (no como funciones de
    Python que el solver tendría que llamar millones de veces): la búsqueda corre unas 3 veces
    más rápido. Las únicas llamadas a Python que quedan son las de `_watch`, que además son las
    que dejan respirar a los otros hilos del servidor mientras se calcula.
    """
    params = problem.params
    n_reloads = params.max_trips_per_vehicle - 1
    full = orders
    # Nodos alternativos de puesta (mismo pedido, menos kilos), después de los pedidos completos.
    partial: list[Order] = []
    for o in full:
        if o.order_id in puesta_ids:
            partial += [replace(o, kg=kg) for kg in puesta_amounts(o.kg)]
    orders = full + partial
    original_kg = {o.order_id: o.kg for o in full}
    shortfall = [0] + [original_kg[o.order_id] - o.kg for o in orders]
    n = len(orders)
    # Nodos: 0 = bodega; 1..len(full) = pedidos completos; luego sus alternativas de puesta;
    # luego n_reloads recargas por camión.
    reload_owner: dict[int, int] = {
        n + 1 + v * n_reloads + r: v for v in range(len(trucks)) for r in range(n_reloads)
    }
    n_nodes = n + 1 + len(reload_owner)
    keys = [DEPOT_KEY] + [o.client_code for o in orders] + [DEPOT_KEY] * len(reload_owner)

    manager = pywrapcp.RoutingIndexManager(n_nodes, len(trucks), 0)
    routing = pywrapcp.RoutingModel(manager)
    reload_idx = {node: manager.NodeToIndex(node) for node in reload_owner}

    # Costo de arco: centavos de diésel según rendimiento (+ EXTRA_TRIP_COST al salir de una recarga).
    cost_cb: dict[float, int] = {}
    max_arc = 0
    for v, truck in enumerate(trucks):
        kmpl = truck.km_per_liter
        if kmpl not in cost_cb:
            table = [
                [
                    round(matrix.km(a, b) * params.diesel_mxn_per_liter / kmpl * 100)
                    + (EXTRA_TRIP_COST if ia in reload_owner else 0)
                    for b in keys
                ]
                for ia, a in enumerate(keys)
            ]
            max_arc = max(max_arc, max(max(row) for row in table))
            for ia in range(1, n + 1):  # kilos que la puesta deja sin entregar
                if shortfall[ia]:
                    table[ia] = [c + shortfall[ia] * DROP_PENALTY_PER_KG for c in table[ia]]
            cost_cb[kmpl] = routing.RegisterTransitMatrix(table)
        routing.SetArcCostEvaluatorOfVehicle(cost_cb[kmpl], v)
        routing.SetFixedCostOfVehicle(1 + round(truck.fixed_dispatch_cost_mxn * 100), v)

    # Capacidad: la recarga vacía el camión vía holgura.
    demands = (
        [0]
        + [o.kg for o in orders]
        + [-trucks[reload_owner[node]].capacity_kg for node in reload_owner]
    )
    demand_cb = routing.RegisterUnaryTransitVector(demands)
    max_cap = max(t.capacity_kg for t in trucks)
    routing.AddDimensionWithVehicleCapacity(
        demand_cb, max_cap, [t.capacity_kg for t in trucks], True, "Capacity"
    )
    capacity = routing.GetDimensionOrDie("Capacity")
    for node in range(1, n + 1):
        capacity.SlackVar(manager.NodeToIndex(node)).SetValue(0)
    for v in range(len(trucks)):
        capacity.SlackVar(routing.Start(v)).SetValue(0)
    for node, idx in reload_idx.items():
        capacity.SlackVar(idx).SetRange(0, trucks[reload_owner[node]].capacity_kg)

    # Tiempo: viaje + lo que tarda el nodo de origen (descarga según sus kilos, o recarga).
    service = (
        [0] + [params.service_time(o.kg) for o in orders] + [params.reload_minutes] * len(reload_owner)
    )
    time_table = [[matrix.minutes(a, b) + service[ia] for b in keys] for ia, a in enumerate(keys)]
    time_cb = routing.RegisterTransitMatrix(time_table)
    # Inicio de la entrega: [más temprano, más tardío] firme (pedido + cliente) y "hasta" blando.
    bounds = {
        node: service_bounds(o, problem.clients[o.client_code], params)
        for node, o in enumerate(orders, start=1)
    }
    # Una entrega que no cabe ni yendo sola (el pedido completo cuando solo cabe su puesta) queda
    # fuera del modelo: sus límites serían contradictorios.
    alone = {
        node: alone_reason(o, problem.clients[o.client_code], params, matrix) is None
        for node, o in enumerate(orders, start=1)
    }
    # Solo un "no antes de" obliga a esperar; con puros límites superiores la holgura sobra.
    needs_wait = any(alone[node] and bounds[node][0] > 0 for node in alone)
    soft = [node for node, o in enumerate(orders, start=1) if alone[node] and o.window_end is not None]
    routing.AddDimension(
        time_cb, params.shift_minutes if needs_wait else 0, params.shift_minutes, True, "Time"
    )
    time_dim = routing.GetDimensionOrDie("Time")
    if needs_wait:
        time_dim.SetSlackCostCoefficientForAllVehicles(WAIT_COST_PER_MIN)
    for node, o in enumerate(orders, start=1):
        idx = manager.NodeToIndex(node)
        if not alone[node]:
            routing.VehicleVar(idx).SetValues([-1])
            continue
        earliest, latest = bounds[node]
        if earliest > 0:
            time_dim.CumulVar(idx).SetMin(earliest)
        if latest is not None and latest < params.shift_minutes:
            time_dim.CumulVar(idx).SetMax(latest)
        if o.window_end is not None:
            time_dim.SetCumulVarSoftUpperBound(idx, o.window_end, LATE_PENALTY_PER_MIN)

    # Contador de viajes: cumul en un pedido = número de viaje - 1.
    trip_inc = [1 if node in reload_owner else 0 for node in range(n_nodes)]
    trip_cb = routing.RegisterUnaryTransitVector(trip_inc)
    routing.AddDimension(trip_cb, 0, n_reloads, True, "Trips")
    trips_dim = routing.GetDimensionOrDie("Trips")

    # Recargas: opcionales, exclusivas de su camión; sin recarga al salir ni dos seguidas.
    # Una recarga justo antes de cerrar (viaje final vacío) se permite: abre la puerta a
    # insertar un viaje nuevo de a un nodo en la búsqueda local; schedule la ignora.
    all_reloads = list(reload_idx.values())
    for v in range(len(trucks)):
        routing.NextVar(routing.Start(v)).RemoveValues(all_reloads)
    for node, idx in reload_idx.items():
        routing.AddDisjunction([idx], 0)
        _allow_only(routing, idx, reload_owner[node])
        routing.NextVar(idx).RemoveValues([r for r in all_reloads if r != idx])

    # Pedidos opcionales con penalización proporcional a los kg, más una constante que supera
    # cualquier costo posible de ruta (así un pedido de 1 kg nunca se descarta por costar más).
    route_cost_bound = max_arc * (n_nodes + 1) + sum(
        1 + round(t.fixed_dispatch_cost_mxn * 100) for t in trucks
    ) + LATE_PENALTY_PER_MIN * params.shift_minutes * len(soft) + (
        WAIT_COST_PER_MIN * params.shift_minutes * len(trucks) if needs_wait else 0
    )
    # Un pedido bloqueado cuesta más descartarlo que todos los libres juntos: la búsqueda nunca
    # cambia uno bloqueado por otros más pesados (y si queda fuera, el bloqueo era imposible).
    penalty = [o.kg * DROP_PENALTY_PER_KG + route_cost_bound for o in full]
    locked_extra = sum(penalty)
    alternatives: dict[str, list[int]] = {}
    for node, o in enumerate(orders, start=1):
        alternatives.setdefault(o.order_id, []).append(manager.NodeToIndex(node))
    for node, o in enumerate(full, start=1):
        extra = locked_extra if o.order_id in problem.locks else 0
        # El pedido completo o una de sus puestas (a lo más uno); ninguno cuesta todo el pedido.
        routing.AddDisjunction(alternatives[o.order_id], penalty[node - 1] + extra, 1)

    # Camiones que no pueden entrar con el cliente (por dimensiones).
    for node, o in enumerate(orders, start=1):
        client = problem.clients.get(o.client_code)
        if client is not None and client.blocked_vehicles:
            allowed = [v for v, t in enumerate(trucks) if client.can_receive(t.vehicle_id)]
            routing.VehicleVar(manager.NodeToIndex(node)).SetValues([-1] + allowed)

    # Bloqueos (camión, viaje).
    node_of = {o.order_id: node for node, o in enumerate(full, start=1)}
    vehicle_of = {t.vehicle_id: v for v, t in enumerate(trucks)}
    for order_id, (vehicle_id, trip_no) in problem.locks.items():
        if order_id in node_of:
            idx = manager.NodeToIndex(node_of[order_id])
            _allow_only(routing, idx, vehicle_of[vehicle_id])
            if trip_no is not None:
                trips_dim.CumulVar(idx).SetRange(trip_no - 1, trip_no - 1)

    # Orden a mano: el rango (paradas contadas desde la salida) crece en el orden fijado.
    sequences = _sequences(problem, set(node_of))
    if sequences:
        rank_cb = routing.RegisterUnaryTransitVector([1] * n_nodes)
        routing.AddDimension(rank_cb, 0, n_nodes + 1, True, "Rank")
        rank = routing.GetDimensionOrDie("Rank")
        solver = routing.solver()
        for _, _, wanted in sequences:
            idxs = [manager.NodeToIndex(node_of[oid]) for oid in wanted]
            for a, b in zip(idxs, idxs[1:]):
                solver.Add(rank.CumulVar(a) < rank.CumulVar(b))

    search = pywrapcp.DefaultRoutingSearchParameters()
    search.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search.time_limit.seconds = params.time_limit_s
    finish = _watch(routing, control, params.time_limit_s, route_cost_bound)
    solution = None
    if sequences or start:
        # La primera solución voraz no ve las restricciones de orden y descarta esos pedidos;
        # partir de rutas que ya traen el orden a mano (o del plan del primer paso) y dejar que
        # la búsqueda agregue el resto.
        routing.CloseModelWithParameters(search)
        if start:
            start_routes = [
                [
                    node
                    for t, trip in enumerate(start.get(truck.vehicle_id, []))
                    for node in ([n + 1 + v * n_reloads + t - 1] if t else []) + [node_of[oid] for oid in trip]
                ]
                for v, truck in enumerate(trucks)
            ]
        else:
            start_routes = _initial_routes(problem, trucks, node_of, n, n_reloads, sequences)
        initial = routing.ReadAssignmentFromRoutes(
            [[manager.NodeToIndex(node) for node in route] for route in start_routes], True
        )
        if initial is not None:
            solution = routing.SolveFromAssignmentWithParameters(initial, search)
    if solution is None:
        solution = routing.SolveWithParameters(search)
    finish()
    if solution is None:
        raise RuntimeError("OR-Tools no encontró solución (no debería: todos los pedidos son opcionales)")

    routes: dict[str, list[list[Order]]] = {}
    served: set[str] = set()
    short: dict[str, int] = {}
    for v, truck in enumerate(trucks):
        trips: list[list[Order]] = [[]]
        idx = solution.Value(routing.NextVar(routing.Start(v)))
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            if node in reload_owner:
                trips.append([])
            else:
                o = orders[node - 1]
                trips[-1].append(o)
                served.add(o.order_id)
                if shortfall[node]:
                    short[o.order_id] = shortfall[node]
            idx = solution.Value(routing.NextVar(idx))
        routes[truck.vehicle_id] = trips
    dropped = [o for o in full if o.order_id not in served]
    return routes, dropped, short


def _initial_routes(
    problem: Problem,
    trucks: list[Vehicle],
    node_of: dict[str, int],
    n: int,
    n_reloads: int,
    sequences: list[tuple[str, int, list[str]]],
) -> list[list[int]]:
    """Nodos por camión con los pedidos bloqueados en (camión, viaje): primero los de orden a
    mano en ese orden, luego el resto del viaje; una recarga entre viajes consecutivos."""
    by_trip: dict[tuple[str, int], list[str]] = {(v, t): list(ids) for v, t, ids in sequences}
    for order_id, (vehicle_id, trip_no) in problem.locks.items():
        if trip_no is not None and order_id in node_of:
            ids = by_trip.setdefault((vehicle_id, trip_no), [])
            if order_id not in ids:
                ids.append(order_id)
    routes: list[list[int]] = []
    for v, truck in enumerate(trucks):
        last = max((t for (vid, t) in by_trip if vid == truck.vehicle_id), default=0)
        route: list[int] = []
        for t in range(1, last + 1):
            if t > 1:
                route.append(n + 1 + v * n_reloads + (t - 2))
            route += [node_of[oid] for oid in by_trip.get((truck.vehicle_id, t), [])]
        routes.append(route)
    return routes


def _watch(
    routing: pywrapcp.RoutingModel, control: SearchControl, time_limit_s: int, all_served_below: int
) -> Callable[[], None]:
    """Vigila la búsqueda: la corta si se cancela desde fuera o si lleva un rato sin mejorar.

    `all_served_below`: un plan que cuesta hasta esto entrega todo (cualquier kilo fuera cuesta
    más). Devuelve la función que hay que llamar al terminar: anota en `control.passes` cómo le
    fue y lanza `SearchCancelled` si la búsqueda se cortó por cancelación.
    """
    started = time.monotonic()
    best_cost: int | None = None
    best_at = 0.0
    improvements = 0
    stopped_by = ""

    def on_solution() -> None:
        nonlocal best_cost, best_at, improvements
        cost = routing.CostVar().Max()
        if best_cost is None or cost < best_cost:
            best_cost, best_at, improvements = cost, time.monotonic() - started, improvements + 1

    def must_stop() -> bool:
        nonlocal stopped_by
        if control.should_stop():
            stopped_by = "cancelado"
            return True
        if control.thorough or best_cost is None:
            return False
        patience = STALL_S if best_cost <= all_served_below else STALL_WITH_KILOS_OUT_S
        if time.monotonic() - started - best_at >= max(patience, STALL_RATIO * best_at):
            stopped_by = "sin_mejora"
            return True
        return False

    routing.AddAtSolutionCallback(on_solution)
    routing.AddSearchMonitor(routing.solver().CustomLimit(must_stop))

    def finish() -> None:
        seconds = time.monotonic() - started
        if stopped_by == "cancelado":
            raise SearchCancelled()
        reason = stopped_by or ("limite" if seconds >= time_limit_s - 0.05 else "fin")
        control.passes.append(SearchStats(seconds, best_at, improvements, reason))

    return finish


def _allow_only(routing: pywrapcp.RoutingModel, index: int, vehicle: int) -> None:
    """Equivale a SetAllowedVehiclesForIndex([vehicle], index) (cuyo binding SWIG falla en
    OR-Tools 9.15); -1 mantiene el nodo descartable por su disyunción."""
    routing.VehicleVar(index).SetValues([-1, vehicle])
