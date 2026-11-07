import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, messageOf } from "../api";
import { kg, lockText } from "../format";
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

export function Orders({ date, onChanged }: Props) {
  const [orders, setOrders] = useState<Order[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [scenarios, setScenarios] = useState<string[]>([]);
  const [scenario, setScenario] = useState("normal");
  const [clientCode, setClientCode] = useState("");
  const [kgValue, setKgValue] = useState("");
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
    const saved = await run(() =>
      api("/api/orders", { method: "POST", body: { date, client_code: code, kg: Number(kgValue) } }),
    );
    if (saved) {
      setClientCode("");
      setKgValue("");
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
        <button type="submit" className="primary">
          Agregar pedido
        </button>
      </form>
      <p className="hint">Si el cliente ya tiene pedido ese día, los kilos se suman al existente.</p>
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
                <th colSpan={2} />
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
