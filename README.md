# HCVRP La Laguna

Planeador de reparto para Graneros Guerra. Para cambiar el logo, reemplaza
`web/src/assets/logo-graneros-guerra.png` y vuelve a compilar la web.


### Arranque
.venv\Scripts\python -m hcvrp.api.seed --snap
.venv\Scripts\python -m hcvrp.api.auth add-user angely
.venv\Scripts\python -m hcvrp.api

A partir de cliente + kilos calcula qué
camión lleva cada pedido, en qué viaje y en qué orden.

## Instalar

Requiere Python 3.11 y Node 20 o más nuevo.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # en Linux/Mac: .venv/bin/python
npm --prefix web install
npm --prefix web run build
```

`data/clients_laguna.json` no se versiona porque contiene datos de clientes;
cópialo a esa ruta antes de sembrar.

## Preparar la base de datos

Guarda la base **fuera de carpetas sincronizadas** como OneDrive o Dropbox: la
sincronización puede dañar un archivo SQLite en uso.

```bash
# PowerShell: $env:HCVRP_DB = "C:\hcvrp\hcvrp.db"
export HCVRP_DB="C:/hcvrp/hcvrp.db"
.venv/Scripts/python -m hcvrp.api.seed
.venv/Scripts/python -m hcvrp.api.auth add-user ana
```

`add-user` pide la contraseña. Con un usuario existente, la cambia y cierra sus
sesiones.

## Arrancar

```bash
.venv/Scripts/python -m hcvrp.api
```

Abre http://127.0.0.1:8000. El HTML se sirve desde `web/dist`, así que arranca
desde la raíz del repositorio.

## Variables de entorno

| Variable | Por defecto | Para qué |
|---|---|---|
| `HCVRP_DB` | `data/hcvrp.db` | Ruta de la base de datos |
| `ORS_API` o `ORS_API_KEY` | | Clave de OpenRouteService |
| `HCVRP_PROVIDER` | `ors` si hay clave; si no, `haversine` | `ors` usa distancias y trazos reales por calles |
| `HCVRP_COOKIE_SECURE` | apagado | Ponla en `1` cuando se sirva por HTTPS |
| `HCVRP_DEBOUNCE_S` | `1.5` | Espera para agrupar cambios antes de recalcular |
| `HCVRP_WEB_DIST` | `web/dist` | Carpeta de la web compilada |
| `HCVRP_HOST`, `PORT` | `127.0.0.1`, `8000` | Dirección del servidor |
| `HCVRP_BASE_PATH` | vacío (raíz) | Prefijo cuando se publica bajo una ruta, p. ej. `/rutas` |

Estas variables también se pueden poner en un archivo `.env` en la raíz, que se
carga al arrancar. Está en `.gitignore`: nunca lo subas al repositorio.

Con `haversine` las distancias son línea recta por un factor de rodeo y la app lo
avisa. Con `ors`, ajusta las ubicaciones sin verificar a la vía más cercana con
`python -m hcvrp.api.seed --snap`.

## Publicar en proadel.app/rutas con Cloudflare Tunnel

La app sigue corriendo en esta máquina; el túnel la expone por HTTPS. En `.env`:

```
HCVRP_BASE_PATH=/rutas
HCVRP_COOKIE_SECURE=1
```

En el túnel, agrega un *public hostname* `proadel.app` con ruta `rutas` (o
`^/rutas`) hacia `http://127.0.0.1:8000`. Usa `127.0.0.1`, no `localhost`: el
servidor solo escucha en IPv4 y confía en la IP del visitante que manda
`cloudflared` solo si la conexión llega desde `127.0.0.1`. Cloudflare no quita el
prefijo, y no debe hacerlo: el servidor ya atiende todo bajo `/rutas`.

La web usa rutas relativas, así que la misma compilación sirve en la raíz o bajo
el prefijo; `/rutas` sin diagonal final redirige a `/rutas/`.

## Cómo calcula

- **Descarga:** cada entrega dura según sus kilos (15 min por tonelada, ajustable en *Flota y
  parámetros*, donde también hay un tiempo fijo por parada). Por eso un pedido grande ocupa buena
  parte de la jornada de un camión.
- **Rápido al editar:** el plan se recalcula solo con cada cambio y se detiene en cuanto deja de
  mejorar (unos 2 s en un día promedio de 14 entregas y 55 t). Si quedan kilos fuera insiste más.
- **A fondo con Recalcular:** el botón usa todo el *Tiempo máximo de cálculo*. Conviene al
  terminar de capturar, sobre todo en días muy cargados.

## Desarrollo

```bash
.venv/Scripts/python -m pytest -q      # motor y API
.venv/Scripts/python -m hcvrp.bench    # mide el motor en días de prueba: kilos, costo y segundos
npm --prefix web test                  # lógica de la web
npm --prefix web run dev               # web con recarga, usa la API en :8000
```

`python -m hcvrp.bench --json antes.json` guarda una corrida; después de cambiar el motor,
`--compare antes.json` muestra la diferencia caso por caso.
