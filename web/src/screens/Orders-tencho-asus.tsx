import { FocusEvent, FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, messageOf } from "../api";
import { clockToMinute, kg, lockText, minuteToClock } from "../format";
import type { Client, Order } from "../types";

type Props = { date: string; onChanged: () => void };

function KgCell({ order, onSave }: { order: Order; onSave: (value: number) => Promise<void> }) {
  const [value, setValue] = useState(String(order.kg));
  useEffect(() => setValue(String(order.kg)), [order.kg]);

  const commit = async () => {
    if (value !== String(order.kg)) await onSave(Number(value));
  };

  return (
    <input
      className="kg-input"
      type="number"
      min={1}
      step={1}
      value={value}
      aria-label={`Kilos de ${order.client_name}`}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur();
      }}
    />
  );
}

type Window = { window_start: number | null; window_end: number | null };

/** Valida dos horas del reloj ("" = sin límite) y las pasa a minutos desde las 09:00. */
function readWindow(from: string, to: string): Window | string {
  const window_start = clockToMinute(from);
  const window_end = clockToMinute(to);
  if (Number.isNaN(window_start) || Number.isNaN(window_end)) return "La hora de entrega debe ser a partir de las 09:00.";
  if (window_start !== null && window_end !== null && window_start >= window_end) {
    return "El horario de entrega debe empezar antes de terminar.";
  }
  return { window_start, window_end };
}

type Hours = { opens_at: string; closes_at: string } | undefined;

function WindowCell({ order, hours, onSave }: { order: Order; hours: Hours; onSave: (w: Window | string) => Promise<void> }) {
  const [from, setFrom] = useState(minuteToClock(order.window_start));
  const [to, setTo] = useState(minuteToClock(order.window_end));
  useEffect(() => {
    setFrom(minuteToClock(order.window_start));
    setTo(minuteToClock(order.window_end));
  }, [order.window_start, order.window_end]);

  // Guarda al salir de la celda (no al pasar de "desde" a "hasta").
  const commit = async (e: FocusEvent<HTMLDivElement>) => {
    if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
    if (from === minuteToClock(order.window_start) && to === minuteToClock(order.window_end)) return;
    await onSave(readWindow(from, to));
  };

  return (
    <div className="window-cell" onBlur={commit}>
      <input type="time" value={from} min={hours?.opens_at} max={hours?.closes_at} onChange={(e) => setFrom(e.target.value)} aria-label={`Entregar a ${order.client_name} desde`} />
      <span aria-hidden="true">a</span>
      <input type="time" value={to} min={hours?.opens_at} max={hours?.closes_at} onChange={(e) => setTo(e.target.value)} aria-label={`Entregar a ${order.client_name} hasta`} />
      {hours && <span className="hours-hint">Recibe {hours.opens_at} a {hours.closes_at}</span>}
    </div>
  );
}

export function Orders({ date, onChanged }: Props) {
  const [orders, setOrders] = useState<Order[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [scenarios, setScenarios] = useState<string[]>([]);
  const [scenario, setScenario] = useState("normal");
  const [clientCode, setClientCode] = useState("");
  const [kgValue, setKgValue] = useState("");
  const [fromValue, setFromValue] = useState("");
  const [toValue, setToValue] = useState("");
  const [error, setError] = useState("");
  const clientInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setOrders(await api<Order[]>(`/api/orders?date=${date}`));
  }, [date]);

  useEffect(() => {
    load().catch((e) => setError(messageOf(e)));
    api<Client[]>("/api/clients").then(setClients).catch((e) => setError(messageOf(e)));
    api<string[]>("/api/scenarios").then(setScenarios).catch(() => {});
  }, [load]);

  const run = async (action: () => Promise<unknown>) => {
    setError("");
    try {
      await action();
      await load();
      onChanged();
      return true;
    } catch (e) {
      setError(messageOf(e));
      await load().catch(() => {});
      return false;
    }
  };

  const add = async (e: FormEvent) => {
    e.preventDefault();
    const code = clientCode.trim().toUpperCase();
    const window = readWindow(fromValue, toValue);
    if (typeof window === "string") {
      setError(window);
      return;
    }
    const saved = await run(() =>
      api("/api/orders", { method: "POST", body: { date, client_code: code, kg: Number(kgValue), ...window } }),
    );
    if (saved) {
      setClientCode("");
      setKgValue("");
      setFromValue("");
      setToValue("");
      clientInput.current?.focus();
    }
  };

  const loadScenario = () => {
    if (orders.length && !window.confirm(`Esto reemplaza los ${orders.length} pedidos de este día. ¿Cargar el escenario?`)) return;
    void run(() => api("/api/orders/scenario", { method: "POST", body: { date, name: scenario } }));
  };

  const remove = (order: Order) => {
    void run(() => api(`/api/orders/${order.id}`, { method: "DELETE" }));
  };

  const total = orders.reduce((sum, o) => sum + o.kg, 0);
  const hoursOf = (code: string): Hours => clients.find((c) => c.code === code);
  const pickedHours = hoursOf(clientCode.trim().toUpperCase());

  return (
    <section className="page narrow">
      <h1>Pedidos del día</h1>

      <form className="capture" onSubmit={add}>
        <label className="grow">
          Cliente
          <input
            ref={clientInput}
            list="client-options"
            value={clientCode}
            onChange={(e) => setClientCode(e.target.value)}
            placeholder="Busca por código o nombre"
            required
          />
          <datalist id="client-options">
            {clients.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
              </option>
            ))}
          </datalist>
        </label>
        <label>
          Kilos
          <input type="number" min={1} step={1} value={kgValue} onChange={(e) => setKgValue(e.target.value)} required />
        </label>
        <fieldset className="window-field">
          <legend>Entregar entre <span className="muted">(opcional)</span></legend>
          <input type="time" value={fromValue} min={pickedHours?.opens_at} max={pickedHours?.closes_at} onChange={(e) => setFromValue(e.target.value)} aria-label="Entregar desde" />
          <span aria-hidden="true">y</span>
          <input type="time" value={toValue} min={pickedHours?.opens_at} max={pickedHours?.closes_at} onChange={(e) => setToValue(e.target.value)} aria-label="Entregar hasta" />
          {pickedHours && <span className="hours-hint">El cliente recibe de {pickedHours.opens_at} a {pickedHours.closes_at}</span>}
        </fieldset>
        <button type="submit" className="primary">
          Agregar pedido
        </button>
      </form>
      <p className="hint">
        Si el cliente ya tiene pedido ese día, los kilos se suman al existente. El horario es opcional: deja vacío un
        lado para decir solo "desde" o solo "antes de". Sin horario, el plan decide cuándo entregar, siempre dentro
        del horario en que recibe el cliente.
      </p>
      {error && <p className="error" role="alert">{error}</p>}

      {orders.length === 0 ? (
        <p className="empty">Este día aún no tiene pedidos. Captura el primero o carga un escenario de prueba.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Cliente</th>
                <th className="num">Kilos</th>
                <th>Horario de entrega</th>
                <th>Asignación</th>
                <th aria-label="Acciones" />
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id}>
                  <td>
                    <strong>{o.client_code}</strong> <span className="muted">{o.client_name}</span>
                  </td>
                  <td className="num">
                    <KgCell
                      order={o}
                      onSave={async (value) => {
                        await run(() => api(`/api/orders/${o.id}`, { method: "PATCH", body: { kg: value } }));
                      }}
                    />
                  </td>
                  <td>
                    <WindowCell
                      order={o}
                      hours={hoursOf(o.client_code)}
                      onSave={async (w) => {
                        if (typeof w === "string") {
                          setError(w);
                          return;
                        }
                        await run(() => api(`/api/orders/${o.id}`, { method: "PATCH", body: w }));
                      }}
                    />
                  </td>
                  <td>{o.lock ? lockText(o.lock) : <span className="muted">La decide el plan</span>}</td>
                  <td className="num">
                    <button type="button" className="link danger" onClick={() => remove(o)}>
                      Borrar
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th>{orders.length} pedidos</th>
                <th className="num">{kg(total)}</th>
                <th colSpan={3} />
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      <div className="scenario">
        <label>
          Escenario de prueba
          <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
            {scenarios.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={loadScenario}>
          Cargar escenario
        </button>
        {orders.length > 0 && <a href="#plan">Ver el plan</a>}
      </div>
    </section>
  );
}
