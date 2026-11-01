# HCVRP La Laguna

Planeador de reparto para Graneros Guerra. Para cambiar el logo, reemplaza
`web/src/assets/logo-graneros-guerra.png` y vuelve a compilar la web.

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
| `HCVRP_PROVIDER` | `haversine` | `ors` usa distancias y trazos reales por calles |
| `ORS_API_KEY` | | Clave de OpenRouteService, necesaria con `ors` |
| `HCVRP_COOKIE_SECURE` | apagado | Ponla en `1` cuando se sirva por HTTPS |
| `HCVRP_DEBOUNCE_S` | `1.5` | Espera para agrupar cambios antes de recalcular |
| `HCVRP_WEB_DIST` | `web/dist` | Carpeta de la web compilada |
| `HCVRP_HOST`, `PORT` | `127.0.0.1`, `8000` | Dirección del servidor |

Con `haversine` las distancias son línea recta por un factor de rodeo y la app lo
avisa. Con `ors`, ajusta las ubicaciones sin verificar a la vía más cercana con
`python -m hcvrp.api.seed --snap`.

## Desarrollo

```bash
.venv/Scripts/python -m pytest -q      # motor y API
npm --prefix web test                  # lógica de la web
npm --prefix web run dev               # web con recarga, usa la API en :8000
```
