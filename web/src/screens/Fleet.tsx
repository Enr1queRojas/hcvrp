import { FormEvent, useEffect, useState } from "react";
import { api, messageOf } from "../api";
import type { Params, Vehicle } from "../types";

const PARAM_FIELDS: { key: keyof Params; label: string; step: number }[] = [
  { key: "diesel_mxn_per_liter", label: "Precio del diésel (MXN por litro)", step: 0.01 },
  { key: "loading_mxn_per_kg", label: "Costo de carga (MXN por kg)", step: 0.01 },
  { key: "shift_minutes", label: "Duración de la jornada (minutos, desde las 9:00)", step: 1 },
  { key: "service_minutes", label: "Tiempo de entrega por cliente (minutos)", step: 1 },
  { key: "reload_minutes", label: "Tiempo de recarga en bodega (minutos)", step: 1 },
  { key: "max_trips_per_vehicle", label: "Viajes máximos por camión", step: 1 },
  { key: "time_limit_s", label: "Tiempo máximo de cálculo (segundos)", step: 1 },
];

export function Fleet({ onChanged }: { onChanged: () => void }) {
  const [fleet, setFleet] = useState<Vehicle[]>([]);
  const [params, setParams] = useState<Params | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api<Vehicle[]>("/api/fleet").then(setFleet).catch((e) => setError(messageOf(e)));
    api<Params>("/api/params").then(setParams).catch((e) => setError(messageOf(e)));
  }, []);

  const updateVehicle = (id: string, change: Partial<Vehicle>) =>
    setFleet((current) => current.map((v) => (v.vehicle_id === id ? { ...v, ...change } : v)));

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setNotice("");
    try {
      await api("/api/fleet", { method: "PUT", body: fleet });
      await api("/api/params", { method: "PUT", body: params });
      setNotice("Cambios guardados. El plan se está recalculando.");
      onChanged();
    } catch (err) {
      setError(messageOf(err));
    }
  };

  return (
    <form className="page narrow" onSubmit={save}>
      <h1>Flota y parámetros</h1>

      <h2>Camiones</h2>
      <p className="hint">Estos datos valen para todos los días: si un camión no sale mañana, recuerda volver a activarlo después.</p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Camión</th>
              <th>Disponible</th>
              <th className="num">Capacidad (kg)</th>
              <th className="num">Rendimiento (km/L)</th>
              <th className="num">Costo fijo por salida (MXN)</th>
            </tr>
          </thead>
          <tbody>
            {fleet.map((v) => (
              <tr key={v.vehicle_id}>
                <td><strong>{v.vehicle_id}</strong></td>
                <td>
                  <input
                    type="checkbox"
                    checked={v.available}
                    aria-label={`${v.vehicle_id} disponible`}
                    onChange={(e) => updateVehicle(v.vehicle_id, { available: e.target.checked })}
                  />
                </td>
                <td className="num">
                  <input
                    className="kg-input" type="number" min={1} step={1} value={v.capacity_kg}
                    aria-label={`Capacidad de ${v.vehicle_id}`}
                    onChange={(e) => updateVehicle(v.vehicle_id, { capacity_kg: Number(e.target.value) })}
                  />
                </td>
                <td className="num">
                  <input
                    className="kg-input" type="number" min={0.1} step={0.1} value={v.km_per_liter}
                    aria-label={`Rendimiento de ${v.vehicle_id}`}
                    onChange={(e) => updateVehicle(v.vehicle_id, { km_per_liter: Number(e.target.value) })}
                  />
                </td>
                <td className="num">
                  <input
                    className="kg-input" type="number" min={0} step={1} value={v.fixed_dispatch_cost_mxn}
                    aria-label={`Costo fijo de ${v.vehicle_id}`}
                    onChange={(e) => updateVehicle(v.vehicle_id, { fixed_dispatch_cost_mxn: Number(e.target.value) })}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>Costos y tiempos</h2>
      {params && (
        <div className="param-grid">
          {PARAM_FIELDS.map(({ key, label, step }) => (
            <label key={key}>
              {label}
              <input
                type="number"
                step={step}
                value={params[key]}
                onChange={(e) => setParams({ ...params, [key]: Number(e.target.value) })}
              />
            </label>
          ))}
        </div>
      )}

      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="ok" role="status">{notice}</p>}
      <button type="submit" className="primary">
        Guardar cambios
      </button>
    </form>
  );
}
