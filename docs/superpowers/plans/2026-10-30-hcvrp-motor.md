# Motor de planeación HCVRP — Plan de implementación (1 de 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Motor Python que, dados clientes, flota, parámetros y pedidos, produce un plan multi‑viaje validado (camión → viajes → paradas), reporta pedidos que pasan al día siguiente con motivo y se compara contra una línea base que imita la planeación intuitiva. Se usa por CLI.

**Architecture:** Paquete `hcvrp` independiente de la web. El solver (OR-Tools) y la línea base solo deciden *secuencias* de pedidos por viaje; un único módulo `schedule` convierte secuencias en horarios, km y costo; un `validate` independiente re‑deriva todo desde la matriz y rechaza planes inválidos. Las distancias vienen de un `DistanceProvider` intercambiable (Haversine offline para pruebas, OpenRouteService `driving-hgv` para uso real) con caché en disco.

**Tech Stack:** Python 3.12, `ortools>=9.10`, `httpx`, `pytest`. Sin base de datos ni web en este plan.

**Spec:** `docs/superpowers/specs/2026-10-30-hcvrp-laguna-design.md`

**Planes siguientes (no en este documento):** Plan 2 — API FastAPI + SQLite + login + recálculo en segundo plano + bloqueos persistentes. Plan 3 — web React/TypeScript/MapLibre (pedidos, clientes con fijar ubicación, flota/parámetros, plan con mapa y geometría ORS, hoja imprimible por camión) + despliegue.

## Global Constraints

- Bodega: `Location(lat=25.528580, lon=-103.373271)`.
- Flota por defecto: V1 10 000 kg 4.0 km/L; V2 20 000 kg 2.8 km/L; V3 20 000 kg 2.8 km/L; V4 30 000 kg 2.2 km/L; `fixed_dispatch_cost_mxn = 0`.
- Parámetros por defecto: diésel 27 MXN/L; carga 0.10 MXN/kg; jornada 480 min (minuto 0 = 9:00); entrega 20 min por parada; recarga 120 min; máximo 3 viajes por camión.
- El viaje 1 sale en el minuto 0 ya cargado (la carga de la tarde anterior no consume jornada). Cada viaje t≥2 empieza exactamente al terminar el anterior + 120 min. Todo camión vuelve a bodega a más tardar en el minuto 480.
- Sin entregas divididas: un pedido va completo en un viaje de un camión. Un pedido por cliente por día; duplicados del mismo cliente se suman.
- Costo de viaje = `km × diésel ÷ km_por_litro + kg_cargados × 0.10`; más `fixed_dispatch_cost_mxn` una vez por camión usado.
- Objetivo: maximizar kg entregados; luego minimizar costo; desempate: menos recargas, luego menos camiones.
- Motivos de no entrega (valores exactos): `excede_capacidad`, `no_cabe_jornada`, `sin_coordenadas`, `saturacion_flota`.
- Semilla de datos sintéticos: `20261030`.
- Tiempos en minutos enteros; distancias en km `float`.
- El repo se inicializa con git en la Tarea 1. Cada mensaje de commit termina con la línea `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Prerequisito de la Tarea 3:** el usuario debe haber copiado `hcvrp_supuestos_v01.json` a `data/`. Si no está, detente y pídelo.

## Review Focus

1. Pedido con kg ≤ 0 → `ValueError` al construir `Order` (prueba en Tarea 1).
2. Pedido de un cliente inexistente → `ValueError` con el código del cliente, antes de resolver (prueba en Tarea 6).
3. Todos los camiones no disponibles → plan sin viajes, todos los pedidos `saturacion_flota`, sin excepción (prueba en Tarea 7).
4. Lista de pedidos vacía → plan vacío con costo 0 (prueba en Tarea 7).
5. OpenRouteService sin `ORS_API_KEY` o con punto no ruteable → error claro que nombra la causa/cliente, nunca una matriz con ceros silenciosos (pruebas en Tarea 2).

---

## Estructura de archivos

```
pyproject.toml
src/hcvrp/
  __init__.py
  domain.py          # dataclasses y enums del dominio; flota y parámetros por defecto
  schedule.py        # secuencias → Trip/VehiclePlan/Plan con horarios, km y costo
  geo/
    __init__.py
    matrix.py        # Matrix, DistanceProvider, HaversineProvider
    cache.py         # CachedProvider (JSON en .cache/matrix/)
    ors.py           # OrsProvider (matriz + snap, driving-hgv)
  data/
    __init__.py
    clients.py       # depuración del JSON fuente y coordenadas sintéticas
  scenarios.py       # escenarios simulados
  validate.py        # validador independiente
  precheck.py        # fusión de duplicados y motivos previos al solver
  solver.py          # OR-Tools multi-viaje
  baseline.py        # vecino más cercano + comparación
  cli.py             # python -m hcvrp.cli
tests/
  conftest.py              # tiny_matrix, problem_ab, plan_ab, clients, problem_for
  fixtures/supuestos_min.json
  test_domain_schedule.py  test_geo.py  test_clients.py  test_scenarios.py
  test_validate.py  test_precheck.py  test_solver.py  test_baseline_cli.py
data/                # fuente (del usuario) y clients_laguna.json generado
```

---

### Task 1: Andamiaje, dominio y `schedule`

**Files:**
- Create: `pyproject.toml`, `.gitignore` (`.venv/`, `.cache/`, `__pycache__/`), `src/hcvrp/__init__.py`, `src/hcvrp/domain.py`, `src/hcvrp/schedule.py`, `tests/conftest.py`
- Test: `tests/test_domain_schedule.py`

**Interfaces:**
- Produces (`domain.py`):
  - `Location(lat: float, lon: float)` frozen
  - `LocationStatus(StrEnum)`: `SINTETICA="sintetica"`, `PENDIENTE="pendiente"`, `VERIFICADA="verificada"`
  - `Client(code: str, name: str, address: str, location: Location | None, location_status: LocationStatus)`
  - `Vehicle(vehicle_id: str, capacity_kg: int, km_per_liter: float, available: bool = True, fixed_dispatch_cost_mxn: float = 0.0)`
  - `Params(diesel_mxn_per_liter=27.0, loading_mxn_per_kg=0.10, shift_minutes=480, service_minutes=20, reload_minutes=120, max_trips_per_vehicle=3, time_limit_s=15)`
  - `Order(order_id: str, client_code: str, kg: int)` — `__post_init__` lanza `ValueError` si `kg <= 0`
  - `UnservedReason(StrEnum)`: `EXCEDE_CAPACIDAD`, `NO_CABE_JORNADA`, `SIN_COORDENADAS`, `SATURACION_FLOTA` (valores en Global Constraints)
  - `Stop(order_id: str, client_code: str, kg: int, arrival_min: int, departure_min: int)`
  - `Trip(trip_no: int, start_min: int, end_min: int, km: float, stops: tuple[Stop, ...])` con propiedad `kg`
  - `VehiclePlan(vehicle_id: str, trips: tuple[Trip, ...])`
  - `Unserved(order_id: str, reason: UnservedReason)`
  - `Plan(vehicles: tuple[VehiclePlan, ...], unserved: tuple[Unserved, ...], cost_mxn: float, km_total: float, liters_total: float, reloads: int, uses_unverified_locations: bool)`
  - `Problem(depot: Location, clients: dict[str, Client], vehicles: list[Vehicle], orders: list[Order], params: Params, locks: dict[str, tuple[str, int]] = {})` — `locks`: `order_id → (vehicle_id, trip_no)`
  - `DEPOT: Location`, `DEFAULT_FLEET: list[Vehicle]`
- Produces (`schedule.py`). Usa la matriz solo por su interfaz `km(a, b)` / `minutes(a, b)` con claves `"DEPOT"` o código de cliente (la clase `Matrix` real llega en la Tarea 2; aquí `conftest.py` define `tiny_matrix` con esa interfaz):
  - `build_trip(trip_no: int, start_min: int, orders: list[Order], matrix, params: Params) -> Trip`
  - `build_vehicle_plan(vehicle_id: str, trips: list[list[Order]], matrix, params: Params) -> VehiclePlan` — omite listas vacías y numera viajes 1..n
  - `summarize(problem: Problem, vehicle_plans: list[VehiclePlan], unserved: list[Unserved], matrix) -> Plan` — omite camiones sin viajes

- [ ] **Step 1: `git init`; crear `pyproject.toml` (paquete `hcvrp` en `src/`, deps `ortools>=9.10`, `httpx`; extra `dev` con `pytest`); `python -m venv .venv`; `pip install -e .[dev]`.** Verifica: `python -c "import ortools, httpx"` sin error.

- [ ] **Step 2: Escribir las pruebas que fallan**

```python
# tiny_matrix: DEPOT→A 10 min 5 km; A→B 15 min 6 km; B→DEPOT 20 min 8 km
def test_build_trip_times_and_km(tiny_matrix):
    t = build_trip(1, 0, [Order("o1", "A", 3000), Order("o2", "B", 4000)], tiny_matrix, Params())
    assert [(s.arrival_min, s.departure_min) for s in t.stops] == [(10, 30), (45, 65)]
    assert t.end_min == 85 and t.km == 19 and t.kg == 7000

def test_second_trip_starts_after_reload(tiny_matrix):
    vp = build_vehicle_plan("V1", [[Order("o1", "A", 3000)], [], [Order("o2", "B", 4000)]], tiny_matrix, Params())
    assert [t.trip_no for t in vp.trips] == [1, 2]
    assert vp.trips[1].start_min == vp.trips[0].end_min + 120

def test_summarize_cost_formula(tiny_matrix, problem_ab):
    vp = build_vehicle_plan("V1", [[Order("o1", "A", 3000), Order("o2", "B", 4000)]], tiny_matrix, Params())
    plan = summarize(problem_ab, [vp], [], tiny_matrix)
    assert plan.cost_mxn == pytest.approx(19 * 27 / 4.0 + 7000 * 0.10)  # 828.25
    assert plan.liters_total == pytest.approx(19 / 4.0) and plan.reloads == 0
    assert plan.uses_unverified_locations is True  # A y B con estado SINTETICA

def test_order_rejects_non_positive_kg():
    with pytest.raises(ValueError):
        Order("o1", "A", 0)
```

- [ ] **Step 3: Ejecutar** `pytest tests/test_domain_schedule.py -v` → FAIL (import).
- [ ] **Step 4: Implementar `domain.py` y `schedule.py`.** Horario: llegada = salida anterior + `minutes(prev, c)`; salida = llegada + `service_minutes`; fin = última salida + `minutes(last, "DEPOT")`. `reloads` = viajes totales − camiones usados. `uses_unverified_locations` = algún cliente servido con estado ≠ `VERIFICADA`.
- [ ] **Step 5: Ejecutar** → PASS.
- [ ] **Step 6: Commit** `feat: dominio y cálculo de horarios/costos`.

---

### Task 2: Distancias — Haversine, caché y OpenRouteService

**Files:**
- Create: `src/hcvrp/geo/__init__.py`, `src/hcvrp/geo/matrix.py`, `src/hcvrp/geo/cache.py`, `src/hcvrp/geo/ors.py`
- Test: `tests/test_geo.py`

**Interfaces:**
- Produces:
  - `Matrix(keys: list[str], km_rows: list[list[float]], min_rows: list[list[int]])` con `km(a: str, b: str) -> float`, `minutes(a: str, b: str) -> int`
  - `class DistanceProvider(Protocol): def matrix(self, points: dict[str, Location]) -> Matrix`
  - `HaversineProvider(detour_factor: float = 1.3, speed_kmh: float = 30.0)` — km = haversine × factor; min = `ceil(km / speed × 60)`
  - `CachedProvider(inner: DistanceProvider, cache_dir: Path = Path(".cache/matrix"))` — clave = sha256 del JSON ordenado de `points` + nombre de clase del proveedor interno
  - `OrsProvider(api_key: str | None = None, client: httpx.Client | None = None)` — `api_key` por defecto de `ORS_API_KEY`; si falta, `RuntimeError("Falta ORS_API_KEY")` al construir. Métodos `matrix(points)` y `snap(points: dict[str, Location], radius_m: int = 350) -> dict[str, Location | None]`.

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_haversine_zero_and_symmetric():
    m = HaversineProvider().matrix({"DEPOT": DEPOT, "A": Location(25.54, -103.42), "B": DEPOT})
    assert m.km("DEPOT", "B") == 0 and m.minutes("DEPOT", "B") == 0
    assert m.km("DEPOT", "A") == m.km("A", "DEPOT") > 0
    assert m.minutes("DEPOT", "A") == math.ceil(m.km("DEPOT", "A") / 30 * 60)

def test_cache_calls_inner_once(tmp_path):
    inner = CountingProvider(HaversineProvider())   # helper en la prueba
    c = CachedProvider(inner, tmp_path)
    pts = {"DEPOT": DEPOT, "A": Location(25.54, -103.42)}
    assert c.matrix(pts).km_rows == c.matrix(pts).km_rows and inner.calls == 1

def test_ors_requires_key(monkeypatch):
    monkeypatch.delenv("ORS_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ORS_API_KEY"):
        OrsProvider()

def test_ors_matrix_parses_and_converts(ors_client):  # httpx.Client(transport=MockTransport)
    # respuesta: distances [[0, 5.2], [5.1, 0]] km; durations [[0, 601], [590, 0]] s
    m = OrsProvider("k", client=ors_client).matrix({"DEPOT": DEPOT, "A": Location(25.54, -103.42)})
    assert m.km("DEPOT", "A") == 5.2 and m.minutes("DEPOT", "A") == 11

def test_ors_unroutable_point_names_client(ors_client_with_null):
    with pytest.raises(ValueError, match="A"):
        OrsProvider("k", client=ors_client_with_null).matrix({"DEPOT": DEPOT, "A": Location(25.54, -103.42)})

def test_ors_snap(ors_snap_client):  # locations: [{"location": [-103.4201, 25.5402]}, null]
    r = OrsProvider("k", client=ors_snap_client).snap({"A": Location(25.54, -103.42), "B": Location(25.0, -103.0)})
    assert r["A"] == Location(25.5402, -103.4201) and r["B"] is None
```

- [ ] **Step 2: Ejecutar** `pytest tests/test_geo.py -v` → FAIL.
- [ ] **Step 3: Implementar.** Matriz ORS: `POST https://api.openrouteservice.org/v2/matrix/driving-hgv`, header `Authorization: <key>`, body `{"locations": [[lon, lat], ...], "metrics": ["distance", "duration"], "units": "km"}`; duraciones en segundos → `ceil(s/60)`; cualquier `null` → `ValueError` con la clave. Snap: `POST https://api.openrouteservice.org/v2/snap/driving-hgv`, body `{"locations": [[lon, lat], ...], "radius": radius_m}`.
- [ ] **Step 4: Ejecutar** → PASS.
- [ ] **Step 5: Commit** `feat: proveedores de distancias con caché`.

---

### Task 3: Clientes de La Laguna

**Files:**
- Create: `src/hcvrp/data/__init__.py`, `src/hcvrp/data/clients.py`, `tests/fixtures/supuestos_min.json` (registros A.ESPARZA, ABEL, ADRIANA, BODEGA con los campos del JSON fuente: `code`, `name_original`, `address_original`, `latitude`, `longitude`, …)
- Generated: `data/clients_laguna.json`
- Test: `tests/test_clients.py`

**Interfaces:**
- Produces:
  - `KEEP_WITH_ADDRESS: frozenset[str]` — los 27 códigos de la spec §5.1
  - `KEEP_PENDING: frozenset[str]` — `ADRIANA, ALAZAN, APOLO, AYUTLA, BERNAL 2, BUGARIN, CAZEROLA, CECY`
  - `SYNTHETIC_BOX = (25.50, 25.60, -103.52, -103.34)` (lat_min, lat_max, lon_min, lon_max; Torreón–Gómez–Lerdo)
  - `prepare_clients(raw_path: Path, seed: int = 20261030) -> list[Client]` — solo códigos de las dos listas; coordenadas nuevas uniformes en `SYNTHETIC_BOX` con `random.Random(seed)` recorriendo los códigos en orden alfabético; estado `SINTETICA` (con dirección) o `PENDIENTE`
  - `save_clients(clients: list[Client], path: Path) -> None`, `load_clients(path: Path) -> dict[str, Client]`
  - `python -m hcvrp.data.clients data/hcvrp_supuestos_v01.json data/clients_laguna.json`

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_filters_and_statuses(fixture_path):
    cs = {c.code: c for c in prepare_clients(fixture_path)}
    assert set(cs) == {"A.ESPARZA", "ADRIANA"}
    assert cs["A.ESPARZA"].location_status is LocationStatus.SINTETICA
    assert cs["ADRIANA"].location_status is LocationStatus.PENDIENTE
    assert all(c.location is not None for c in cs.values())

def test_coordinates_in_box_and_deterministic(fixture_path):
    a, b = prepare_clients(fixture_path), prepare_clients(fixture_path)
    assert a == b
    assert all(25.50 <= c.location.lat <= 25.60 and -103.52 <= c.location.lon <= -103.34 for c in a)

def test_keep_lists_sizes():
    assert len(KEEP_WITH_ADDRESS) == 27 and len(KEEP_PENDING) == 8

def test_roundtrip(tmp_path, fixture_path):
    cs = prepare_clients(fixture_path); save_clients(cs, tmp_path / "c.json")
    assert load_clients(tmp_path / "c.json") == {c.code: c for c in cs}
```

- [ ] **Step 2: Ejecutar** → FAIL. **Step 3: Implementar.** **Step 4: Ejecutar** → PASS.
- [ ] **Step 5: Generar** `data/clients_laguna.json`; verificar `python -c "import json;print(len(json.load(open('data/clients_laguna.json'))))"` → `35`.
- [ ] **Step 6: Commit** `feat: depuración de clientes de La Laguna` con `data/clients_laguna.json`. Preguntar al usuario antes de versionar el JSON fuente (contiene nombres reales).

---

### Task 4: Escenarios simulados

**Files:** Create `src/hcvrp/scenarios.py`; Test `tests/test_scenarios.py`

**Interfaces:**
- Consumes: `Client`, `Order`
- Produces: `SCENARIOS = ("ligero", "normal", "pesado", "inviable")`; `generate_scenario(name: str, clients: dict[str, Client], seed: int = 20261030) -> list[Order]`; `order_id = f"{name}-{i:02d}"`; kg múltiplos de 100.

Reglas: clientes distintos elegidos con `random.Random(seed)`.
- ligero: 12 pedidos, total objetivo 40 000; normal: 20 / 80 000; pesado: 28 / 120 000. Tamaños: 80 % uniforme 1 000–6 000, 20 % uniforme 8 000–15 000; escalar al total y recortar a [500, 15 000].
- inviable: 20 pedidos; uno de 35 000 kg y 19 uniformes 12 000–15 000 (V1 no puede llevar ninguno; V2/V3 uno por viaje, V4 dos → máximo 12 en 3 viajes, satura por diseño).

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
@pytest.mark.parametrize("name,n,total", [("ligero", 12, 40_000), ("normal", 20, 80_000), ("pesado", 28, 120_000)])
def test_sizes_and_totals(clients, name, n, total):
    s = generate_scenario(name, clients)
    assert len(s) == n and len({o.client_code for o in s}) == n
    assert 0.85 * total <= sum(o.kg for o in s) <= 1.15 * total
    assert all(500 <= o.kg <= 15_000 and o.kg % 100 == 0 for o in s)

def test_inviable(clients):
    s = generate_scenario("inviable", clients)
    assert len(s) == 20 and sum(o.kg > 30_000 for o in s) == 1
    assert all(12_000 <= o.kg <= 15_000 for o in s if o.kg <= 30_000)

def test_deterministic(clients):
    assert generate_scenario("normal", clients) == generate_scenario("normal", clients)
```

- [ ] **Steps 2–4:** FAIL → implementar → PASS. **Step 5: Commit** `feat: escenarios de pedidos simulados`.

---

### Task 5: Validador independiente

**Files:** Create `src/hcvrp/validate.py`; Test `tests/test_validate.py`

**Interfaces:**
- Consumes: `Problem`, `Plan`, `Matrix`
- Produces: `validate(problem: Problem, plan: Plan, matrix: Matrix) -> list[str]` (vacía = válido; cada texto describe una violación en español e incluye el id de camión, viaje o pedido).

Comprobaciones, re‑derivadas desde la matriz **sin importar `schedule`**: cada pedido (tras fusión) aparece exactamente una vez, servido o no servido; kg de parada = kg del pedido; kg del viaje ≤ capacidad; solo camiones disponibles; viajes ≤ `max_trips_per_vehicle`; viaje 1 empieza en 0; viaje t≥2 empieza en fin(t−1) + 120; horarios y km coinciden con la matriz; fin ≤ 480; bloqueos respetados; costo, litros y recargas recalculados coinciden (tolerancia 0.01).

- [ ] **Step 1: Escribir las pruebas que fallan.** `plan_ab` (en `conftest.py`) es un plan válido construido con `schedule`; cada prueba de violación lo muta con `dataclasses.replace`:

```python
def test_valid_plan(problem_ab, plan_ab, tiny_matrix):
    assert validate(problem_ab, plan_ab, tiny_matrix) == []
# una prueba por caso, cada una afirma que alguna violación contiene el texto indicado:
# sobrecarga (kg 12 000 en V1)        → "capacidad"
# regreso tarde (end_min=481)          → "480"
# pedido faltante (quitar o2)          → "o2"
# pedido duplicado (o1 dos veces)      → "o1"
# recarga corta (inicio = fin + 60)    → "recarga"
# costo alterado (+1 MXN)              → "costo"
# bloqueo {"o1": ("V2", 1)} no cumplido → "bloqueo"
```

- [ ] **Steps 2–4:** FAIL → implementar → PASS. **Step 5: Commit** `feat: validador de planes`.

---

### Task 6: Prechequeo y fusión de pedidos

**Files:** Create `src/hcvrp/precheck.py`; Test `tests/test_precheck.py`

**Interfaces:**
- Produces:
  - `merge_orders(orders: list[Order]) -> list[Order]` — suma por `client_code`; conserva el `order_id` del primero
  - `precheck(problem: Problem, matrix: Matrix) -> tuple[list[Order], list[Unserved]]` — devuelve (planeables, no servidos) sobre los pedidos ya fusionados. En este orden: cliente inexistente → `ValueError` con el código; `location is None` → `SIN_COORDENADAS`; kg > mayor capacidad **disponible** → `EXCEDE_CAPACIDAD`; `minutes(DEPOT,c) + service + minutes(c,DEPOT) > shift` → `NO_CABE_JORNADA`. Bloqueo a camión no disponible o con `trip_no > max_trips_per_vehicle` → `ValueError`.
  - `points_for(problem: Problem) -> dict[str, Location]` — `"DEPOT"` + clientes de los pedidos que tienen `location`; lo usan solver y línea base para pedir la matriz.

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_merge_same_client():
    assert merge_orders([Order("a", "X", 3000), Order("b", "X", 2000)]) == [Order("a", "X", 5000)]
# casos (cada uno: reasons = {u.order_id: u.reason for u in precheck(...)[1]})
# cliente "NOEXISTE"                       → pytest.raises(ValueError, match="NOEXISTE")
# cliente con location=None                → {"o1": SIN_COORDENADAS}
# pedido de 35 000 kg                      → {"o1": EXCEDE_CAPACIDAD}
# pedido de 25 000 kg con V4 no disponible → {"o1": EXCEDE_CAPACIDAD}
# DEPOT↔C 240 min cada sentido (240+20+240 > 480) → {"o1": NO_CABE_JORNADA}
# bloqueo a V4 no disponible / trip_no=4   → pytest.raises(ValueError)
```

- [ ] **Steps 2–4:** FAIL → implementar → PASS. **Step 5: Commit** `feat: prechequeo de pedidos inviables`.

---

### Task 7: Solver multi‑viaje (OR-Tools)

**Files:** Create `src/hcvrp/solver.py`; Test `tests/test_solver.py`

**Interfaces:**
- Consumes: `points_for`, `precheck`, `build_vehicle_plan`, `summarize`, `validate`, `DistanceProvider`
- Produces: `solve(problem: Problem, provider: DistanceProvider) -> tuple[Plan, Matrix]` — pide la matriz sobre `points_for(problem)`, corre `precheck`, resuelve, arma el plan con `summarize` y **lanza `AssertionError` con las violaciones si `validate` no devuelve `[]`**.

Modelo (lo que la firma no determina):
- Nodos: 0 = bodega; 1..n = pedidos planeables. Sin pedidos planeables o sin camiones disponibles → no llamar a OR-Tools; devolver plan vacío (o todo `SATURACION_FLOTA`).
- Vehículos virtuales: por camión disponible k y t = 1..`max_trips_per_vehicle`, una copia (k,t) con inicio/fin en bodega y la capacidad del camión.
- Costo de arco por copia: `round(km × diésel ÷ km_por_litro(k) × 100)` centavos (`SetArcCostEvaluatorOfVehicle`).
- Dimensión de capacidad: demanda = kg del pedido.
- Dimensión de tiempo: tránsito `minutes(i,j) + (service si i es pedido)`, holgura 0, horizonte `shift_minutes`. Copia (k,1): cumul de inicio fijo en 0. Copia (k,t≥2): `start(k,t) ≥ end(k,t−1) + reload × activo(k,t−1)` y `activo(k,t) ≤ activo(k,t−1)` con `routing.ActiveVehicleVar`.
- Disyunción por pedido, penalización `kg × 100_000` centavos (1 000 MXN/kg; supera cualquier costo de ruta → maximiza kg entregados).
- Costos fijos: copia t=1 → `1 + round(fixed_dispatch_cost_mxn × 100)`; copia t≥2 → `10` (desempates: menos recargas, luego menos camiones).
- Bloqueos: `SetAllowedVehiclesForIndex([índice de copia (k,t)], índice del nodo)`.
- Búsqueda: `PATH_CHEAPEST_ARC` + `GUIDED_LOCAL_SEARCH`, límite `time_limit_s`.
- Extracción: por camión, secuencias de las copias activas en orden de t → `build_vehicle_plan` (que renumera). Nodos descartados → `SATURACION_FLOTA`. El horario final lo calcula `schedule` (sin esperas), que nunca es más tardío que el del solver.

- [ ] **Step 1: Escribir las pruebas que fallan.** `problem_for(name)` (en `conftest.py`) arma un `Problem` con `DEPOT`, `DEFAULT_FLEET`, `Params(time_limit_s=5)`, 35 clientes sintéticos (generados con `SYNTHETIC_BOX` y la semilla, sin depender de `data/`) y `generate_scenario(name, ...)`.

```python
@pytest.mark.parametrize("name", ["ligero", "normal", "pesado"])
def test_all_served_and_valid(problem_for, name):
    p = problem_for(name); plan, m = solve(p, HaversineProvider())
    assert plan.unserved == () and validate(p, plan, m) == []

def test_pesado_needs_reloads(problem_for):
    plan, _ = solve(problem_for("pesado"), HaversineProvider())
    assert plan.reloads >= 1
    assert all(t.end_min <= 480 for v in plan.vehicles for t in v.trips)

def test_inviable_reasons(problem_for):
    plan, _ = solve(problem_for("inviable"), HaversineProvider())
    reasons = [u.reason for u in plan.unserved]
    assert reasons.count(UnservedReason.EXCEDE_CAPACIDAD) == 1
    assert UnservedReason.SATURACION_FLOTA in reasons

def test_lock_respected(problem_for):
    p = problem_for("ligero"); oid = p.orders[0].order_id
    plan, _ = solve(replace(p, locks={oid: ("V2", 1)}), HaversineProvider())
    trip = next(t for v in plan.vehicles if v.vehicle_id == "V2" for t in v.trips if t.trip_no == 1)
    assert oid in {s.order_id for s in trip.stops}

def test_unavailable_vehicle_unused(problem_for):
    p = problem_for("ligero"); fleet = [replace(v, available=v.vehicle_id != "V4") for v in p.vehicles]
    plan, _ = solve(replace(p, vehicles=fleet), HaversineProvider())
    assert "V4" not in {v.vehicle_id for v in plan.vehicles}

def test_no_orders(problem_for):
    plan, _ = solve(replace(problem_for("ligero"), orders=[]), HaversineProvider())
    assert plan.vehicles == () and plan.cost_mxn == 0

def test_no_vehicles_available(problem_for):
    p = problem_for("ligero"); fleet = [replace(v, available=False) for v in p.vehicles]
    plan, _ = solve(replace(p, vehicles=fleet), HaversineProvider())
    assert plan.vehicles == () and {u.reason for u in plan.unserved} == {UnservedReason.SATURACION_FLOTA}
```

- [ ] **Step 2: Ejecutar** `pytest tests/test_solver.py -v` → FAIL.
- [ ] **Step 3: Implementar** según el modelo.
- [ ] **Step 4: Ejecutar** → PASS (cada prueba ≲ 10 s).
- [ ] **Step 5: Commit** `feat: solver multi-viaje con OR-Tools`.

---

### Task 8: Línea base, comparación y CLI

**Files:** Create `src/hcvrp/baseline.py`, `src/hcvrp/cli.py`; Test `tests/test_baseline_cli.py`

**Interfaces:**
- Consumes: `points_for`, `precheck`, `build_vehicle_plan`, `summarize`, `validate`, `solve`, `load_clients`, `generate_scenario`
- Produces:
  - `baseline_plan(problem: Problem, provider: DistanceProvider) -> tuple[Plan, Matrix]` — camiones disponibles de mayor a menor capacidad; para cada uno, viaje a viaje: desde la posición actual ir al pedido pendiente más cercano (en minutos) que quepa en capacidad y permita volver a bodega ≤ 480; si no hay, regresar; si quedan pedidos y tiempo para recarga + otro viaje, recargar; hasta `max_trips_per_vehicle`. Restantes → `SATURACION_FLOTA`. Debe pasar `validate`.
  - `Comparison(served_kg_diff: int, cost_diff_mxn: float, optimized_is_better_or_equal: bool)`; `compare(optimized: Plan, baseline: Plan, problem: Problem) -> Comparison` — primero kg entregados (más gana), a igualdad costo (menor o igual gana, tolerancia 0.01).
  - `main(argv: list[str] | None = None) -> int` en `cli.py`; uso: `python -m hcvrp.cli solve --scenario {ligero,normal,pesado,inviable} [--provider haversine|ors] [--clients data/clients_laguna.json] [--out plan.json]`. Imprime: resumen (costo, km, litros, recargas, camiones), "Carga de esta tarde" (viaje 1 por camión: kg y clientes), viajes con paradas y horas `HH:MM` (minuto 0 = 09:00), no servidos con motivo, aviso "ubicaciones no verificadas" si aplica, y "Línea base" con la comparación. `--provider ors` usa `CachedProvider(OrsProvider())`.

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
@pytest.mark.parametrize("name", SCENARIOS)
def test_baseline_valid(problem_for, name):
    p = problem_for(name); plan, m = baseline_plan(p, HaversineProvider())
    assert validate(p, plan, m) == []

@pytest.mark.parametrize("name", SCENARIOS)
def test_optimized_not_worse(problem_for, name):
    p = problem_for(name)
    c = compare(solve(p, HaversineProvider())[0], baseline_plan(p, HaversineProvider())[0], p)
    assert c.optimized_is_better_or_equal

def test_cli_prints_sections(capsys, clients_file):  # clients_file: save_clients de los 35 sintéticos en tmp_path
    assert main(["solve", "--scenario", "ligero", "--clients", str(clients_file)]) == 0
    out = capsys.readouterr().out
    for s in ("Carga de esta tarde", "09:00", "Línea base", "ubicaciones no verificadas"):
        assert s in out
```

- [ ] **Steps 2–4:** FAIL → implementar → PASS.
- [ ] **Step 5: Verificación completa:** `pytest -v` → todo PASS; `python -m hcvrp.cli solve --scenario pesado` muestra al menos una recarga.
- [ ] **Step 6: Commit** `feat: línea base, comparación y CLI`.
