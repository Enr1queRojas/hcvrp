# Diseño: planeador de reparto HCVRP — La Laguna

Fecha: 2026-10-30
Estado: borrador para aprobación

## 1. Intención y porqué

Hoy el reparto del día siguiente se decide por intuición: quien planea arma
circuitos a partir del recuerdo mental de dónde están los clientes. No hay
herramienta, no hay mapa, no hay medición de costo.

Queremos una webapp que, a partir de **cliente + kilos de cada pedido**,
calcule qué camión lleva cada pedido, en qué viaje y en qué orden, de modo que
el plan sea **más barato que el intuitivo y siempre quepa en la jornada**.

La app apoya a quien planea; no lo sustituye. El plan debe poder entenderse en
un mapa (orden de paradas, km, horarios) para que la persona confíe en él o
detecte dónde no le cuadra.

## 2. Usuarios y momento de uso

- **Usuarios:** una o dos personas, cada una en un lugar distinto. La app debe
  estar publicada en internet, con datos compartidos y acceso con usuario y
  contraseña. Sin roles ni permisos finos.
- **Momento:** por la tarde, cuando regresan los camiones. En ese momento ya se
  conocen **todos** los pedidos del día siguiente (no entran pedidos después).
- **Flujo:**
  1. Capturar pedidos del día siguiente (cliente + kg).
  2. La app calcula el plan.
  3. Se carga cada camión esa misma tarde con su **viaje 1**.
  4. Al día siguiente, los camiones salen a las 9:00; las recargas y viajes
     posteriores ocurren durante la jornada según el plan.

## 3. Reglas operativas (decididas)

| Regla | Valor |
|---|---|
| Bodega (depósito único) | 25.528580, -103.373271 (real) |
| Flota | V1 10 000 kg, V2 20 000 kg, V3 20 000 kg, V4 30 000 kg |
| Inicio de jornada | 9:00, camión ya cargado (la carga del viaje 1 se hace la tarde anterior, fuera de jornada) |
| Duración de jornada | 480 min (9:00–17:00), incluye manejo, entregas y recargas |
| Tiempo de entrega | 20 min por cliente visitado |
| Recarga en bodega | 120 min por recarga, solo en bodega |
| Viajes por camión | Múltiples (bodega → clientes → bodega → recarga → …) |
| Fin de jornada | Cada camión debe estar de regreso en bodega a más tardar a las 17:00 |
| Entregas divididas | No: cada pedido completo en un solo viaje de un solo camión |
| Inventario | Suficiente en bodega (no es restricción en el MVP) |
| Ventanas horarias por cliente | No en el MVP |
| Volumen | No es restricción en el MVP |
| Zona de servicio | Solo La Laguna |

**Pedidos inviables** se muestran explícitamente con su motivo. Motivos mínimos:
- excede la capacidad del camión más grande (> 30 000 kg);
- no cabe en la jornada de ningún camión (tiempo);
- cliente sin coordenadas (solo puede ocurrir con un cliente dado de alta
  sin ubicación; los clientes con ubicación sintética o pendiente **sí se
  planean**, con aviso — ver §5.1);
- no cabe por saturación de la flota: el pedido cabría solo, pero la flota no
  alcanza a cubrir todos los pedidos del día (motivo distinto de "no cabe en
  la jornada de ningún camión", que significa que ni solo cabe).

## 4. Objetivo de optimización (decidido)

1. Entregar todos los pedidos posibles. Cuando no caben todos, **no hay
   clientes prioritarios**: la optimización decide cuáles pasan al día
   siguiente (decisión del usuario). Regla concreta (mi decisión): penalización
   por pedido no entregado proporcional a sus kg y muy superior a cualquier
   costo de ruta, de modo que se maximizan los kg entregados y, a igualdad, se
   minimiza el costo. Los pedidos que quedan fuera se reportan como "pasa al
   día siguiente" con su motivo (§3).
2. Minimizar el costo de operación:
   `costo_viaje = km × 27 MXN/L ÷ rendimiento_km_L(camión) + kg_cargados × 0.10 MXN/kg`
   (más `fixed_dispatch_cost_mxn`, hoy 0).
3. Desempate: menos recargas; después, menos camiones usados.

Indicador mostrado (no objetivo): clientes atendidos por viaje.

Nota para el builder: el costo de carga por kg es constante si se entregan
todos los pedidos; solo influye cuando hay pedidos no entregados. Las recargas
no tienen costo monetario explícito; su costo real es el tiempo (120 min) que
ya consume jornada.

Parámetros de costo (editables en la app, valores ilustrativos del archivo de
supuestos v0.1): diésel 27 MXN/L; rendimientos V1 4.0, V2 2.8, V3 2.8,
V4 2.2 km/L; carga 0.10 MXN/kg.

## 5. Datos

### 5.1 Clientes

Fuente: `data/hcvrp_supuestos_v01.json` (50 registros, todas las coordenadas
sintéticas; campos por cliente: `code`, `name_original`, `address_original`,
`latitude`, `longitude`, `coordinate_status`, `demand_kg` (null),
`review_required`; además trae bodega de prueba, flota y supuestos de costo).
El usuario debe colocar el archivo en esa ruta antes de empezar. Se depuran
así:

**Conservar — La Laguna con dirección (27):** A.ESPARZA, A.ESPARZA3, AARON,
ABSALON, ADAN, ADRIAN, ANTUNEZ, ARREDONDO, ARREOLA, BARBAS, BEATRIZ,
BEATRIZ 2, BENJA2, BENJAMIN, BERNARDO, BETO, BRETADO, CABRERA, CAMACHO,
CAMARILLO, CAMBIO, CAMBIO2, CARLOS, CARLOS C, CARLOS2, CAVAZOS, CELIA CAR2.

**Conservar — sin dirección, ubicación pendiente (8):** ADRIANA, ALAZAN,
APOLO, AYUTLA, BERNAL 2, BUGARIN, CAZEROLA, CECY. Reciben coordenadas
sintéticas y se planean normalmente, con aviso (el usuario autorizó usar
datos sintéticos mientras recopila las direcciones).

**Eliminar (15):**
- Fuera de La Laguna: ABEL, AGROEXP, CARGILL, CAMPO51, CENTRAL, ADALBERTO,
  AVARIOSMTY, CANATLAN, ABRAM FERH.
- No son clientes de reparto: AAVARIOS, BANCOMER, BASCULA REVUE., BODEGA
  (BODEGA es la propia bodega de salida).

Total MVP: **35 clientes**.

**Ubicaciones:** todas siguen siendo sintéticas. El usuario recopilará las
reales. Por tanto:
- Cada cliente tiene un estado de ubicación: `sintética` | `pendiente` |
  `verificada`.
- La app permite **fijar la ubicación de un cliente en el mapa** (clic o
  arrastrar el punto) una sola vez y guardarla como `verificada`.
- Todo plan que incluya clientes no verificados muestra un aviso visible.
- Las coordenadas sintéticas deben regenerarse dentro de una zona urbana
  plausible de Torreón–Gómez Palacio–Lerdo alrededor de la nueva bodega, con
  semilla fija (20261030), y ajustarse a la vía más cercana (snap) para que el
  servicio de rutas las acepte.
- Altas, bajas y edición de clientes (nombre, dirección, ubicación) desde la
  app.

### 5.2 Pedidos simulados

No hay pedidos reales ni un día histórico para comparar. Se generan
escenarios de prueba reproducibles (semilla fija), por ejemplo:

| Escenario | Clientes con pedido | kg totales aprox. | Propósito |
|---|---:|---:|---|
| Ligero | ~12 | ~40 000 | Cabe en un solo viaje por camión |
| Normal | ~20 | ~80 000 | Uso cercano a la capacidad de la flota en un viaje |
| Pesado | ~28 | ~120 000 | Obliga a recargas / segundos viajes |
| Inviable | ~20 | — | Incluye un pedido > 30 000 kg y carga que excede la jornada |

Distribución sugerida de tamaño: mayoría 1 000–6 000 kg, algunos
8 000–15 000 kg. Un pedido por cliente por día (si se capturan dos para el
mismo cliente, se suman en una sola parada siempre que no se exceda la
capacidad máxima; si se excede, es inviable por capacidad).

Los escenarios se pueden cargar desde la app con un botón ("cargar escenario
de prueba") y también se usan en las pruebas automatizadas.

## 6. Comportamiento de la app

### 6.1 Pantallas / funciones

- **Pedidos del día:** tabla para capturar cliente (buscador por código/nombre)
  + kg; editar y borrar; cargar escenario simulado.
- **Clientes:** lista + mapa; fijar ubicación; estado de ubicación.
- **Flota y parámetros:** capacidades, disponibilidad por camión (un camión
  puede marcarse no disponible ese día), rendimientos, precio del diésel, costo
  de carga, horario de jornada, tiempo de entrega, tiempo de recarga.
- **Plan:**
  - Resumen: costo total, km totales, litros, recargas, camiones usados,
    pedidos inviables con motivo.
  - **Carga de esta tarde:** por camión, kg y pedidos del viaje 1.
  - Por camión → viajes → paradas: orden, cliente, kg, hora estimada de
    llegada y salida, km del viaje, kg cargados, % de capacidad usada.
  - Mapa con la ruta de cada camión/viaje (color por camión, distinción por
    viaje) sobre la geometría real de calles.
  - **Hoja imprimible por camión** (para el chofer): viajes, paradas en orden,
    kg, horas estimadas.
  - Comparación contra una línea base sencilla (ver §8).

### 6.2 Recálculo

Al editar pedidos o parámetros, el plan se recalcula automáticamente tras una
breve espera que agrupa cambios. Mientras calcula se muestra el último
resultado marcado como "desactualizado"; solo se reemplaza cuando llega el
resultado correspondiente al estado vigente de los datos. El cálculo tiene un
límite de tiempo (orden de 10–30 s) y no bloquea la interfaz.

### 6.3 Ajuste manual (mi decisión, alcance mínimo)

Quien planea puede mover un pedido a otro camión/viaje o fijarlo ("bloquear").
La app recalcula horarios, km y costo del plan ajustado, lo valida contra las
reglas (capacidad, jornada) y muestra la diferencia de costo frente al plan
óptimo. Si el ajuste viola una regla, se indica cuál.

Semántica (mi decisión): un bloqueo fija el pedido a **camión + viaje**; el
orden de paradas dentro del viaje lo sigue decidiendo el solver. Los bloqueos
se guardan y son restricciones duras en todo recálculo automático posterior
hasta que el usuario los quita. La diferencia de costo se compara contra el
plan óptimo sin bloqueos.

## 7. Arquitectura (decisiones mías, cambiables)

La propuesta original (worker separado, versiones de planes, PostgreSQL,
monorepo con paquetes) está dimensionada para muchos usuarios y replaneación
continua. Con 1–2 usuarios y un cálculo al día se simplifica:

- **Backend:** un solo servicio Python (FastAPI). El cálculo corre en un
  proceso/hilo de fondo dentro del mismo servicio.
- **Motor de optimización:** módulo Python independiente de la web (entrada:
  pedidos, flota, parámetros, matriz de distancias/tiempos; salida: plan).
  Recomendado: Google OR-Tools (routing). El modelado de múltiples viajes con
  recarga de 120 min y jornada compartida queda a criterio del builder.
- **Validador independiente:** función que, dado un plan, verifica todas las
  reglas de §3 y recalcula el costo de §4. Se usa en pruebas y para ajustes
  manuales. Ningún plan se muestra sin pasar el validador.
- **Distancias y tiempos:** adaptador a un servicio de rutas con perfil de
  camión pesado. Recomendado: OpenRouteService (perfil `driving-hgv`, plan
  gratuito suficiente para ~36 puntos). Matriz y geometrías se guardan en caché
  y solo se vuelven a pedir cuando cambia la ubicación de un cliente o de la
  bodega. Para pruebas sin red, un proveedor alterno de distancia en línea
  recta × factor de rodeo.
- **Base de datos:** SQLite (o PostgreSQL administrado si el hosting no ofrece
  disco persistente). Entidades: clientes, pedidos (por fecha), flota,
  parámetros, planes calculados.
- **Frontend:** React + TypeScript + MapLibre, con mapa base de teselas
  gratuitas.
- **Acceso:** login con usuario y contraseña para 1–2 cuentas.
- **Hosting:** un proveedor barato con HTTPS. Elección del builder.

Jerarquía del plan: **Plan → camión → viajes → paradas → pedidos.**

## 8. Cómo sabremos que funciona

- Todos los escenarios simulados producen planes que pasan el validador.
- El escenario inviable reporta los pedidos inviables con el motivo correcto.
- El escenario pesado produce recargas y respeta las 17:00.
- Comparación contra una **línea base** que imita la intuición (p. ej.
  vecino más cercano, llenando primero el camión más grande). La línea base
  también respeta capacidad y jornada. Se compara primero pedidos entregados
  (el optimizado debe entregar ≥) y, a igualdad, costo (el optimizado debe
  costar ≤). La app muestra la diferencia.
- A futuro (fuera del MVP): capturar un plan hecho a mano por quien planea y
  compararlo con el de la app.

## 9. Objetivos, no‑objetivos y anti‑objetivos

**Objetivos MVP:** capturar pedidos; calcular plan multi‑viaje con flota
heterogénea; ver plan en mapa y tablas; carga de la tarde; hojas por camión;
fijar ubicaciones de clientes; escenarios simulados; inviables con motivo.

**No‑objetivos MVP:** replaneación durante la ruta; ventanas horarias;
entregas divididas; restricción de volumen o inventario; múltiples bodegas;
app para choferes; clientes fuera de La Laguna; costos de chofer,
mantenimiento, llantas, casetas.

**Anti‑objetivos (sería un fracaso aunque "funcione"):**
- Un plan que parezca barato pero no quepa en 9:00–17:00.
- Un plan presentado como confiable cuando usa ubicaciones sintéticas sin
  avisarlo.
- Un plan que quien planea no pueda entender ni ajustar.

## 10. Pendientes de información (no bloquean el MVP)

- Ubicaciones reales de los 35 clientes.
- Rendimiento real de diésel por camión y precio real del diésel.
- Modelo/configuración de cada camión (el de 30 t podría ser tractocamión) y
  restricciones viales.
- Costos fijos por salida, si existen.

## 11. Lo que queda a criterio del builder

Modelado matemático de múltiples viajes, estrategia del solver y límites de
tiempo; estructura de carpetas; proveedor de hosting y de teselas; diseño
visual; formato exacto de la hoja imprimible; parámetros exactos de los
escenarios simulados dentro de lo descrito en §5.2.
