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

Por construcción los viajes se usan en orden (t usado => t-1 usado) y no hay viajes
vacíos intermedios (sin recarga justo al salir ni dos recargas seguidas); un viaje final
vacío (recarga justo antes de cerrar) se descarta al armar el plan.
Con copias por vehículo y restricciones de CP entre sus cumuls, la búsqueda local de
OR-Tools 9.15 rechazaba todo movimiento (descartaba todos los pedidos).

El horario final lo recalcula `schedule.build_vehicle_plan` (sin esperas), que coincide
con el del solver (holgura de tiempo 0).
"""
from __future__ import annotations

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from hcvrp.domain import Order, Plan, Problem, Unserved, UnservedReason, Vehicle
from hcvrp.geo.matrix import DistanceProvider, Matrix
from hcvrp.precheck import points_for, precheck
from hcvrp.schedule import DEPOT_KEY, build_vehicle_plan, summarize
from hcvrp.validate import validate

DROP_PENALTY_PER_KG = 100_000  # centavos por kg (1 000 MXN/kg)
EXTRA_TRIP_COST = 10  # centavos por recarga; desempate: menos recargas


def solve(problem: Problem, provider: DistanceProvider) -> tuple[Plan, Matrix]:
    matrix = provider.matrix(points_for(problem))
    planeable, unserved = precheck(problem, matrix)
    trucks = [v for v in problem.vehicles if v.available]

    if not planeable:
        routes: dict[str, list[list[Order]]] = {}
    elif not trucks:
        routes = {}
        unserved = unserved + [Unserved(o.order_id, UnservedReason.SATURACION_FLOTA) for o in planeable]
    else:
        routes, dropped = _route(problem, matrix, planeable, trucks)
        _check_locks_honored(problem, planeable, routes)
        unserved = unserved + [Unserved(o.order_id, UnservedReason.SATURACION_FLOTA) for o in dropped]

    vehicle_plans = [
        build_vehicle_plan(vid, trips, matrix, problem.params) for vid, trips in routes.items()
    ]
    plan = summarize(problem, vehicle_plans, unserved, matrix)
    violations = validate(problem, plan, matrix)
    if violations:
        raise AssertionError("plan inválido:\n" + "\n".join(violations))
    return plan, matrix


def _check_locks_honored(
    problem: Problem, planeable: list[Order], routes: dict[str, list[list[Order]]]
) -> None:
    planeable_ids = {o.order_id for o in planeable}
    for order_id, (vehicle_id, trip_no) in problem.locks.items():
        if order_id not in planeable_ids:
            continue
        trips = routes.get(vehicle_id, [])
        if not (trip_no <= len(trips) and any(o.order_id == order_id for o in trips[trip_no - 1])):
            raise ValueError(
                f"bloqueo infeasible: el pedido {order_id!r} no pudo servirse en el camión "
                f"{vehicle_id!r}, viaje {trip_no} (capacidad, jornada o viajes insuficientes)"
            )


def _route(
    problem: Problem, matrix: Matrix, orders: list[Order], trucks: list[Vehicle]
) -> tuple[dict[str, list[list[Order]]], list[Order]]:
    params = problem.params
    n_reloads = params.max_trips_per_vehicle - 1
    n = len(orders)
    # Nodos: 0 = bodega; 1..n = pedidos; luego n_reloads recargas por camión.
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
            cost_cb[kmpl] = routing.RegisterTransitCallback(
                lambda i, j, table=table: table[manager.IndexToNode(i)][manager.IndexToNode(j)]
            )
        routing.SetArcCostEvaluatorOfVehicle(cost_cb[kmpl], v)
        routing.SetFixedCostOfVehicle(1 + round(truck.fixed_dispatch_cost_mxn * 100), v)

    # Capacidad: la recarga vacía el camión vía holgura.
    demands = (
        [0]
        + [o.kg for o in orders]
        + [-trucks[reload_owner[node]].capacity_kg for node in reload_owner]
    )
    demand_cb = routing.RegisterUnaryTransitCallback(lambda i: demands[manager.IndexToNode(i)])
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

    # Tiempo: viaje + servicio en el nodo de origen (entrega o recarga). Holgura 0.
    service = [0] + [params.service_minutes] * n + [params.reload_minutes] * len(reload_owner)
    time_table = [[matrix.minutes(a, b) + service[ia] for b in keys] for ia, a in enumerate(keys)]
    time_cb = routing.RegisterTransitCallback(
        lambda i, j: time_table[manager.IndexToNode(i)][manager.IndexToNode(j)]
    )
    routing.AddDimension(time_cb, 0, params.shift_minutes, True, "Time")

    # Contador de viajes: cumul en un pedido = número de viaje - 1.
    trip_inc = [1 if node in reload_owner else 0 for node in range(n_nodes)]
    trip_cb = routing.RegisterUnaryTransitCallback(lambda i: trip_inc[manager.IndexToNode(i)])
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
    )
    for node, o in enumerate(orders, start=1):
        routing.AddDisjunction(
            [manager.NodeToIndex(node)], o.kg * DROP_PENALTY_PER_KG + route_cost_bound
        )

    # Bloqueos (camión, viaje).
    node_of = {o.order_id: node for node, o in enumerate(orders, start=1)}
    vehicle_of = {t.vehicle_id: v for v, t in enumerate(trucks)}
    for order_id, (vehicle_id, trip_no) in problem.locks.items():
        if order_id in node_of:
            idx = manager.NodeToIndex(node_of[order_id])
            _allow_only(routing, idx, vehicle_of[vehicle_id])
            trips_dim.CumulVar(idx).SetRange(trip_no - 1, trip_no - 1)

    search = pywrapcp.DefaultRoutingSearchParameters()
    search.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search.time_limit.seconds = params.time_limit_s
    solution = routing.SolveWithParameters(search)
    if solution is None:
        raise RuntimeError("OR-Tools no encontró solución (no debería: todos los pedidos son opcionales)")

    routes: dict[str, list[list[Order]]] = {}
    served: set[int] = set()
    for v, truck in enumerate(trucks):
        trips: list[list[Order]] = [[]]
        idx = solution.Value(routing.NextVar(routing.Start(v)))
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            if node in reload_owner:
                trips.append([])
            else:
                trips[-1].append(orders[node - 1])
                served.add(node)
            idx = solution.Value(routing.NextVar(idx))
        routes[truck.vehicle_id] = trips
    dropped = [o for node, o in enumerate(orders, start=1) if node not in served]
    return routes, dropped


def _allow_only(routing: pywrapcp.RoutingModel, index: int, vehicle: int) -> None:
    """Equivale a SetAllowedVehiclesForIndex([vehicle], index) (cuyo binding SWIG falla en
    OR-Tools 9.15); -1 mantiene el nodo descartable por su disyunción."""
    routing.VehicleVar(index).SetValues([-1, vehicle])
