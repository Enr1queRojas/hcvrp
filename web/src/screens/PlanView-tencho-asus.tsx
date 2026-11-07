import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, messageOf } from "../api";
import { RouteMap } from "../components/RouteMap";
import { ShiftTimeline } from "../components/ShiftTimeline";
import { TruckSheet } from "../components/TruckSheet";
import { hhmm, kg, km, mxn, tripColor, truckColors, windowText } from "../format";
import { moveStop, shiftStop, type Trips } from "../sequence";
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
  // Orden arrastrado que aún no llega en un plan recalculado (se muestra mientras tanto).
  const [reordered, setReordered] = useState<Record<string, Trips>>({});
  const [drag, setDrag] = useState<{ vehicle: string; id: string } | null>(null);
  const [hint, setHint] = useState<{ id: string; after: boolean } | null>(null);
  const focusAfterMove = useRef<string | null>(null);

  useEffect(() => {
    if (status?.status !== "calculando") setReordered({});
  }, [status?.computed_at, status?.status]);

  useEffect(() => {
    if (!focusAfterMove.current) return;
    document.querySelector<HTMLButtonElement>(`[data-handle="${focusAfterMove.current}"]`)?.focus();
    focusAfterMove.current = null;
  });

  const stopPrinting = useCallback(() => setPrinting(null), []);
  const colorOf = useMemo(() => truckColors(fleet.map((v) => v.vehicle_id)), [fleet]);

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

  const setTruck = (orderId: string, vehicleId: string) => {
    void change(() =>
      vehicleId
        ? api(`/api/orders/${orderId}/lock`, { method: "PUT", body: { vehicle_id: vehicleId } })
        : api(`/api/orders/${orderId}/lock`, { method: "DELETE" }),
    );
  };

  /** Guarda el nuevo orden de un camión y lo muestra al instante mientras se recalcula el plan. */
  const commitOrder = async (vehicleId: string, trips: Trips) => {
    setReordered((prev) => ({ ...prev, [vehicleId]: trips }));
    setError("");
    try {
      await api("/api/orders/sequence", {
        method: "PUT",
        body: { date, vehicle_id: vehicleId, trips: trips.map((t) => t.map(Number)) },
      });
      await load();
      onChanged();
    } catch (e) {
      setReordered(({ [vehicleId]: _, ...rest }) => rest);
      setError(messageOf(e));
    }
  };

  const clearOrder = (vehicleId: string) => {
    void change(() =>
      api(`/api/orders/sequence?date=${date}&vehicle_id=${encodeURIComponent(vehicleId)}`, { method: "DELETE" }),
    );
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
  const trucks = fleet.filter((v) => v.available).map((v) => v.vehicle_id);

  const assignment = (orderId: string, clientCode: string, clientName: string) => {
    const lock = lockOf(orderId);
    const blocked = clients.find((c) => c.code === clientCode)?.blocked_vehicles ?? [];
    const fit = trucks.filter((id) => !blocked.includes(id));
    const options = lock && !fit.includes(lock.vehicle_id) ? [...fit, lock.vehicle_id] : fit;
    return (
      <div className="assign">
        <select
          aria-label={`Camión para el pedido de ${clientName}`}
          value={lock?.vehicle_id ?? ""}
          data-locked={Boolean(lock)}
          onChange={(e) => setTruck(orderId, e.target.value)}
        >
          <option value="">Lo decide el plan</option>
          {options.map((id) => <option key={id} value={id}>Fijo en {id}</option>)}
        </select>
      </div>
    );
  };

  const dropAt = (vehicleId: string, trips: Trips, targetId: string, after: boolean) => {
    if (drag?.vehicle === vehicleId) {
      const next = moveStop(trips, drag.id, targetId, after);
      if (JSON.stringify(next) !== JSON.stringify(trips)) void commitOrder(vehicleId, next);
    }
    setDrag(null);
    setHint(null);
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
            {plan.summary.late_stops > 0 && (
              <div data-alert="true"><dt>Entregas fuera de horario</dt><dd>{plan.summary.late_stops}</dd></div>
            )}
            {plan.summary.puesta_stops > 0 && (
              <div data-signal="true"><dt>Entregas en puesta</dt><dd>{plan.summary.puesta_stops}</dd></div>
            )}
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
          <ShiftTimeline fleet={fleet} vehicles={plan.vehicles} params={params} colorOf={colorOf} only={only} onSelect={setOnly} />

          <div className="plan-columns">
            <RouteMap vehicles={plan.vehicles} clients={clients} depot={config.depot} colorOf={colorOf} only={only} />
            <div>
              <h2>Carga de esta tarde</h2>
              <p className="hint">Lo que se sube hoy a cada camión para salir a las 09:00.</p>
              <table>
                <thead><tr><th>Camión</th><th className="num">Kilos</th><th className="num">Pedidos</th><th className="num">Capacidad</th></tr></thead>
                <tbody>
                  {plan.afternoon_load.map((load) => (
                    <tr key={load.vehicle_id}>
                      <td><strong style={{ color: colorOf(load.vehicle_id) }}>{load.vehicle_id}</strong></td>
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
                  <thead><tr><th>Cliente</th><th className="num">Kilos</th><th>Motivo</th><th>Camión</th></tr></thead>
                  <tbody>
                    {plan.unserved.map((u) => (
                      <tr key={u.order_id}>
                        <td><strong>{u.client_code}</strong> <span className="muted">{u.client_name}</span></td>
                        <td className="num">{kg(u.kg)}</td>
                        <td>
                          {u.reason_label}
                          {u.reason === "sin_coordenadas" && <> <a href="#clientes">Fijar ubicación</a></>}
                        </td>
                        <td>{assignment(u.order_id, u.client_code, u.client_name)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          <h2>Viajes y paradas</h2>
          <p className="hint">
            Arrastra una parada por su asa ⠿ para cambiar el orden de entrega o pasarla a otro viaje del mismo camión
            (con el teclado: enfoca el asa y usa las flechas ↑ ↓). Para cambiarla de camión usa la lista de la derecha.
          </p>
          {plan.vehicles.map((vehicle) => {
            const vid = vehicle.vehicle_id;
            const stops = new Map(vehicle.trips.flatMap((t) => t.stops.map((s) => [s.order_id, s] as const)));
            const pending = reordered[vid];
            const trips: Trips = pending ?? vehicle.trips.map((t) => t.stops.map((s) => s.order_id));
            const manual = [...stops.keys()].some((id) => lockOf(id)?.position != null);
            return (
              <details key={vid} className="truck" open style={{ borderColor: colorOf(vid) }}>
                <summary>
                  <strong>Camión {vid}</strong>
                  <span className="muted">{trips.length} {trips.length === 1 ? "viaje" : "viajes"}, capacidad {kg(vehicle.capacity_kg)}</span>
                  {manual && (
                    <span className="manual-order">
                      Orden fijado a mano{" "}
                      <button type="button" className="link" onClick={(e) => { e.preventDefault(); clearOrder(vid); }}>
                        Que lo decida el plan
                      </button>
                    </span>
                  )}
                  <button type="button" className="link" onClick={(e) => { e.preventDefault(); setPrinting(vehicle); }}>
                    Imprimir hoja
                  </button>
                </summary>
                {trips.map((ids, t) => {
                  const trip = pending ? undefined : vehicle.trips[t];
                  return (
                    <div key={t} className="trip-block">
                      <h3 style={{ borderLeft: `6px solid ${tripColor(colorOf(vid), t + 1)}`, paddingLeft: "0.5rem" }}>
                        {trip
                          ? `Viaje ${trip.trip_no}: ${hhmm(trip.start_min)} a ${hhmm(trip.end_min)}, ${km(trip.km)}, ${kg(trip.kg)} (${trip.capacity_pct}% de la capacidad)`
                          : `Viaje ${t + 1}: recalculando horarios con el nuevo orden…`}
                      </h3>
                      <div className="table-wrap">
                        <table>
                          <thead><tr><th>Parada</th><th>Cliente</th><th className="num">Kilos</th><th>Llega</th><th>Sale</th><th>Camión</th></tr></thead>
                          <tbody>
                            {ids.map((id, i) => {
                              const stop = stops.get(id);
                              if (!stop) return null;
                              return (
                                <tr
                                  key={id}
                                  data-drop={hint?.id === id ? (hint.after ? "after" : "before") : undefined}
                                  data-dragging={drag?.id === id || undefined}
                                  onDragOver={(e) => {
                                    if (drag?.vehicle !== vid) return;
                                    e.preventDefault();
                                    const box = e.currentTarget.getBoundingClientRect();
                                    const after = e.clientY > box.top + box.height / 2;
                                    if (hint?.id !== id || hint.after !== after) setHint({ id, after });
                                  }}
                                  onDrop={(e) => {
                                    e.preventDefault();
                                    if (hint) dropAt(vid, trips, hint.id, hint.after);
                                  }}
                                >
                                  <td className="stop-no">
                                    <button
                                      type="button"
                                      className="handle"
                                      draggable
                                      data-handle={id}
                                      aria-label={`Mover la parada de ${stop.client_name}, ahora parada ${i + 1} del viaje ${t + 1}. Usa las flechas arriba y abajo.`}
                                      title="Arrastra para cambiar el orden"
                                      onDragStart={(e) => {
                                        e.dataTransfer.effectAllowed = "move";
                                        e.dataTransfer.setData("text/plain", id);
                                        const row = e.currentTarget.closest("tr");
                                        if (row) e.dataTransfer.setDragImage(row, 16, 16);
                                        setDrag({ vehicle: vid, id });
                                      }}
                                      onDragEnd={() => { setDrag(null); setHint(null); }}
                                      onKeyDown={(e) => {
                                        if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
                                        e.preventDefault();
                                        const next = shiftStop(trips, id, e.key === "ArrowUp" ? -1 : 1);
                                        if (next === trips) return;
                                        focusAfterMove.current = id;
                                        void commitOrder(vid, next);
                                      }}
                                    >
                                      ⠿
                                    </button>
                                    {i + 1}
                                  </td>
                                  <td>
                                    <strong>{stop.client_code}</strong> <span className="muted">{stop.client_name}</span>
                                    {(stop.window_start !== null || stop.window_end !== null) && (
                                      <span className="window-tag">Horario: {windowText(stop.window_start, stop.window_end)}</span>
                                    )}
                                  </td>
                                  <td className="num">
                                    {kg(stop.kg)}
                                    {stop.kg < stop.ordered_kg && (
                                      <span className="puesta-tag">puesta, de {kg(stop.ordered_kg)}</span>
                                    )}
                                  </td>
                                  <td>
                                    {pending ? "…" : (
                                      <>
                                        <span data-late={stop.late_min > 0 || undefined}>{hhmm(stop.arrival_min)}</span>
                                        {stop.late_min > 0 && <span className="late-tag">{stop.late_min} min tarde</span>}
                                        {stop.wait_min > 0 && <span className="wait-tag">espera {stop.wait_min} min</span>}
                                      </>
                                    )}
                                  </td>
                                  <td>{pending ? "…" : hhmm(stop.departure_min)}</td>
                                  <td>{assignment(stop.order_id, stop.client_code, stop.client_name)}</td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  );
                })}
              </details>
            );
          })}
        </div>
      )}
      {printing && <TruckSheet date={date} vehicle={printing} clients={clients} onDone={stopPrinting} />}
    </section>
  );
}
