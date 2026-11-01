import { useCallback, useEffect, useState } from "react";
import { api, messageOf } from "../api";
import { RouteMap } from "../components/RouteMap";
import { ShiftTimeline } from "../components/ShiftTimeline";
import { TruckSheet } from "../components/TruckSheet";
import { hhmm, kg, km, mxn, truckColor } from "../format";
import type { Client, Config, Order, Params, Plan, PlanStatus, Vehicle, VehiclePlan } from "../types";

type Props = {
  date: string;
  status: PlanStatus | null;
  config: Config;
  onChanged: () => void;
};

function comparisonText(plan: Plan): string {
  const { served_kg_diff: kgDiff, cost_diff_mxn: costDiff } = plan.comparison;
  const cost =
    Math.abs(costDiff) < 0.01
      ? "cuesta lo mismo"
      : costDiff < 0
        ? `cuesta ${mxn(-costDiff)} menos`
        : `cuesta ${mxn(costDiff)} más`;
  const served =
    kgDiff === 0 ? "entrega los mismos kilos" : kgDiff > 0 ? `entrega ${kg(kgDiff)} más` : `entrega ${kg(-kgDiff)} menos`;
  return `Frente a armar las rutas por cercanía, llenando primero el camión más grande (${mxn(plan.baseline.cost_mxn)}), este plan ${served} y ${cost}.`;
}

export function PlanView({ date, status, config, onChanged }: Props) {
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [clients, setClients] = useState<Client[]>([]);
  const [fleet, setFleet] = useState<Vehicle[]>([]);
  const [params, setParams] = useState<Params | null>(null);
  const [only, setOnly] = useState<string | null>(null);
  const [printing, setPrinting] = useState<VehiclePlan | null>(null);
  const [error, setError] = useState("");

  const stopPrinting = useCallback(() => setPrinting(null), []);

  const load = useCallback(async () => {
    const [o, c, f, p] = await Promise.all([
      api<Order[]>(`/api/orders?date=${date}`),
      api<Client[]>("/api/clients"),
      api<Vehicle[]>("/api/fleet"),
      api<Params>("/api/params"),
    ]);
    setOrders(o);
    setClients(c);
    setFleet(f);
    setParams(p);
  }, [date]);

  useEffect(() => {
    load().catch((e) => setError(messageOf(e)));
  }, [load, status?.computed_at, status?.status]);

  const change = async (action: () => Promise<unknown>) => {
    setError("");
    try {
      await action();
      await load();
      onChanged();
    } catch (e) {
      setError(messageOf(e));
    }
  };

  const moveTo = (orderId: string, value: string) => {
    const [vehicle_id, trip] = value.split("|");
    void change(() =>
      api(`/api/orders/${orderId}/lock`, { method: "PUT", body: { vehicle_id, trip_no: Number(trip) } }),
    );
  };
  const unlock = (orderId: string) => {
    void change(() => api(`/api/orders/${orderId}/lock`, { method: "DELETE" }));
  };

  if (!status || !orders || !params) return <section className="page"><h1>Plan</h1>{error && <p className="error" role="alert">{error}</p>}</section>;

  if (orders.length === 0) {
    return (
      <section className="page narrow">
        <h1>Plan</h1>
        <p className="empty">Este día no tiene pedidos. <a href="#pedidos">Captura pedidos</a> para calcular el plan.</p>
      </section>
    );
  }

  const plan = status.plan;
  const lockOf = (orderId: string) => orders.find((o) => String(o.id) === orderId)?.lock ?? null;
  const moveOptions = fleet
    .filter((v) => v.available)
    .flatMap((v) =>
      Array.from({ length: params.max_trips_per_vehicle }, (_, i) => ({
        value: `${v.vehicle_id}|${i + 1}`,
        label: `${v.vehicle_id}, viaje ${i + 1}`,
      })),
    );

  const assignment = (orderId: string, clientName: string) => {
    const lock = lockOf(orderId);
    return (
      <div className="assign">
        {lock && (
          <span className="locked">
            Fijado en {lock.vehicle_id}, viaje {lock.trip_no}{" "}
            <button type="button" className="link" onClick={() => unlock(orderId)}>Quitar</button>
          </span>
        )}
        <select
          aria-label={`Fijar el pedido de ${clientName}`}
          value=""
          onChange={(e) => e.target.value && moveTo(orderId, e.target.value)}
        >
          <option value="">{lock ? "Mover a…" : "Fijar en…"}</option>
          {moveOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>
    );
  };

  return (
    <section className="page">
      <div className="plan-head">
        <h1>Plan</h1>
        <button type="button" onClick={() => change(() => api(`/api/plan/recalcular?date=${date}`, { method: "POST" }))}>
          Recalcular
        </button>
      </div>

      {error && <p className="error" role="alert">{error}</p>}
      {status.status === "calculando" && (
        <p className="notice busy" role="status">
          {plan ? "Calculando con los últimos cambios. Lo que ves abajo está desactualizado." : "Calculando el plan. Tarda unos segundos."}
        </p>
      )}
      {status.status === "error" && (
        <p className="notice problem" role="alert">
          No se pudo calcular el plan: {status.error}.
          {plan ? " Lo que ves abajo es el último plan válido, y ya está desactualizado." : ""}
        </p>
      )}
      {plan?.uses_unverified_locations && (
        <p className="notice signal">
          Este plan usa {plan.unverified_clients.length} ubicaciones sin verificar, así que sus rutas, horas y costos son
          orientativos. <a href="#clientes">Fijar ubicaciones</a>
        </p>
      )}
      {config.provider === "haversine" && (
        <p className="notice signal">
          Las distancias se estiman en línea recta, no por calles. Las líneas del mapa solo unen las paradas en orden.
        </p>
      )}

      {plan && (
        <div className={status.stale || status.status !== "listo" ? "plan-body stale" : "plan-body"}>
          <dl className="summary">
            <div><dt>Costo total</dt><dd>{mxn(plan.summary.cost_mxn)}</dd></div>
            <div><dt>Distancia</dt><dd>{km(plan.summary.km_total)}</dd></div>
            <div><dt>Diésel</dt><dd>{plan.summary.liters_total.toFixed(1)} L</dd></div>
            <div><dt>Recargas</dt><dd>{plan.summary.reloads}</dd></div>
            <div><dt>Camiones usados</dt><dd>{plan.summary.vehicles_used}</dd></div>
            <div><dt>Se entrega</dt><dd>{kg(plan.summary.served_kg)}</dd></div>
            <div data-alert={plan.summary.unserved_kg > 0}><dt>Pasa a otro día</dt><dd>{kg(plan.summary.unserved_kg)}</dd></div>
          </dl>
          <p className="comparison">{comparisonText(plan)}</p>
          {plan.lock_cost_diff_mxn !== null && (
            <p className="comparison">
              {plan.lock_cost_diff_mxn > 0.01
                ? `Los pedidos fijados a mano cuestan ${mxn(plan.lock_cost_diff_mxn)} más que el plan sin fijar.`
                : plan.lock_cost_diff_mxn < -0.01
                  ? `Con los pedidos fijados a mano el costo baja ${mxn(-plan.lock_cost_diff_mxn)}, pero entrega menos kilos que el plan sin fijar.`
                  : "Los pedidos fijados a mano no encarecen el plan."}
            </p>
          )}

          <h2>La jornada de cada camión</h2>
          <ShiftTimeline fleet={fleet} vehicles={plan.vehicles} params={params} only={only} onSelect={setOnly} />

          <div className="plan-columns">
            <RouteMap vehicles={plan.vehicles} clients={clients} depot={config.depot} only={only} />
            <div>
              <h2>Carga de esta tarde</h2>
              <p className="hint">Lo que se sube hoy a cada camión para salir a las 09:00.</p>
              <table>
                <thead><tr><th>Camión</th><th className="num">Kilos</th><th className="num">Pedidos</th><th className="num">Capacidad</th></tr></thead>
                <tbody>
                  {plan.afternoon_load.map((load) => (
                    <tr key={load.vehicle_id}>
                      <td><strong style={{ color: truckColor(load.vehicle_id) }}>{load.vehicle_id}</strong></td>
                      <td className="num">{kg(load.kg)}</td>
                      <td className="num">{load.orders}</td>
                      <td className="num">{load.capacity_pct}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {plan.unserved.length > 0 && (
            <>
              <h2>Pasan a otro día</h2>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Cliente</th><th className="num">Kilos</th><th>Motivo</th><th>Asignación</th></tr></thead>
                  <tbody>
                    {plan.unserved.map((u) => (
                      <tr key={u.order_id}>
                        <td><strong>{u.client_code}</strong> <span className="muted">{u.client_name}</span></td>
                        <td className="num">{kg(u.kg)}</td>
                        <td>
                          {u.reason_label}
                          {u.reason === "sin_coordenadas" && <> <a href="#clientes">Fijar ubicación</a></>}
                        </td>
                        <td>{assignment(u.order_id, u.client_name)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          <h2>Viajes y paradas</h2>
          {plan.vehicles.map((vehicle) => (
            <details key={vehicle.vehicle_id} className="truck" open style={{ borderColor: truckColor(vehicle.vehicle_id) }}>
              <summary>
                <strong>Camión {vehicle.vehicle_id}</strong>
                <span className="muted">{vehicle.trips.length} {vehicle.trips.length === 1 ? "viaje" : "viajes"}, capacidad {kg(vehicle.capacity_kg)}</span>
                <button type="button" className="link" onClick={(e) => { e.preventDefault(); setPrinting(vehicle); }}>
                  Imprimir hoja
                </button>
              </summary>
              {vehicle.trips.map((trip) => (
                <div key={trip.trip_no} className="trip-block">
                  <h3>
                    Viaje {trip.trip_no}: {hhmm(trip.start_min)} a {hhmm(trip.end_min)}, {km(trip.km)}, {kg(trip.kg)} ({trip.capacity_pct}% de la capacidad)
                  </h3>
                  <div className="table-wrap">
                    <table>
                      <thead><tr><th>Parada</th><th>Cliente</th><th className="num">Kilos</th><th>Llega</th><th>Sale</th><th>Asignación</th></tr></thead>
                      <tbody>
                        {trip.stops.map((stop, i) => (
                          <tr key={stop.order_id}>
                            <td>{i + 1}</td>
                            <td><strong>{stop.client_code}</strong> <span className="muted">{stop.client_name}</span></td>
                            <td className="num">{kg(stop.kg)}</td>
                            <td>{hhmm(stop.arrival_min)}</td>
                            <td>{hhmm(stop.departure_min)}</td>
                            <td>{assignment(stop.order_id, stop.client_name)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </details>
          ))}
        </div>
      )}
      {printing && <TruckSheet date={date} vehicle={printing} clients={clients} onDone={stopPrinting} />}
    </section>
  );
}
