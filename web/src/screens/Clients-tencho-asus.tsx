import maplibregl, { Map as MapLibre, Marker } from "maplibre-gl";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, messageOf } from "../api";
import { createMap } from "../components/RouteMap";
import type { Client, Config, Vehicle } from "../types";

const STATUS_LABEL: Record<Client["location_status"], string> = {
  sintetica: "Sintética",
  pendiente: "Pendiente",
  verificada: "Verificada",
};

type Props = { config: Config; onChanged: () => void };

export function Clients({ config, onChanged }: Props) {
  const [clients, setClients] = useState<Client[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [onlyUnverified, setOnlyUnverified] = useState(false);
  const blankDraft = { code: "", name: "", address: "", opens_at: "09:00", closes_at: "18:00" };
  const [draft, setDraft] = useState(blankDraft);
  const [edit, setEdit] = useState({
    name: "", address: "", opens_at: "09:00", closes_at: "18:00", blocked_vehicles: [] as string[], puesta: false,
  });
  const [fleet, setFleet] = useState<Vehicle[]>([]);
  const [error, setError] = useState("");
  const [map, setMap] = useState<MapLibre | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const markers = useRef<Marker[]>([]);
  const selectedRef = useRef<string | null>(null);
  selectedRef.current = selected;

  const load = useCallback(async () => {
    setClients(await api<Client[]>("/api/clients"));
  }, []);

  const current = clients.find((c) => c.code === selected) ?? null;

  useEffect(() => {
    if (current) {
      setEdit({
        name: current.name, address: current.address, opens_at: current.opens_at, closes_at: current.closes_at,
        blocked_vehicles: current.blocked_vehicles, puesta: current.puesta,
      });
    }
  }, [current?.code, current?.name, current?.address, current?.opens_at, current?.closes_at, current?.blocked_vehicles.join("|"), current?.puesta]);

  const run = useCallback(async (action: () => Promise<unknown>) => {
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
  }, [load, onChanged]);

  const place = useCallback((code: string, lat: number, lon: number) => {
    void run(() => api(`/api/clients/${encodeURIComponent(code)}/location`, { method: "PUT", body: { lat, lon } }));
  }, [run]);

  useEffect(() => {
    load().catch((e) => setError(messageOf(e)));
    api<Vehicle[]>("/api/fleet").then(setFleet).catch((e) => setError(messageOf(e)));
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    let created: MapLibre | null = null;
    void createMap(container.current!, config.depot).then((m) => {
      if (cancelled) return m.remove();
      created = m;
      m.on("click", (e) => {
        if (selectedRef.current) place(selectedRef.current, e.lngLat.lat, e.lngLat.lng);
      });
      m.on("load", () => setMap(m));
    });
    return () => {
      cancelled = true;
      created?.remove();
    };
  }, [config.depot, place]);

  useEffect(() => {
    if (!map) return;
    markers.current.forEach((m) => m.remove());
    const depot = document.createElement("div");
    depot.className = "depot-marker";
    depot.title = "Bodega";
    const next = [new maplibregl.Marker({ element: depot }).setLngLat([config.depot.lon, config.depot.lat]).addTo(map)];
    for (const c of clients) {
      if (c.lat === null || c.lon === null) continue;
      const el = document.createElement("button");
      el.type = "button";
      el.className = `client-marker status-${c.location_status}${c.code === selected ? " selected" : ""}`;
      el.title = `${c.code}: ${c.name}`;
      el.setAttribute("aria-label", el.title);
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        setSelected(c.code);
      });
      const marker = new maplibregl.Marker({ element: el, draggable: c.code === selected })
        .setLngLat([c.lon, c.lat])
        .addTo(map);
      marker.on("dragend", () => {
        const { lat, lng } = marker.getLngLat();
        place(c.code, lat, lng);
      });
      next.push(marker);
    }
    markers.current = next;
  }, [map, clients, selected, config.depot, place]);

  useEffect(() => {
    if (map && current?.lat != null && current.lon != null) {
      map.easeTo({ center: [current.lon, current.lat], duration: 300 });
    }
  }, [map, current?.code]);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    const code = draft.code.trim();
    const saved = await run(() => api("/api/clients", { method: "POST", body: { ...draft, code } }));
    if (saved) {
      setDraft(blankDraft);
      setSelected(code);
    }
  };

  const saveEdit = (e: FormEvent) => {
    e.preventDefault();
    void run(() => api(`/api/clients/${encodeURIComponent(selected!)}`, { method: "PATCH", body: edit }));
  };

  const remove = async () => {
    if (!current || !window.confirm(`¿Borrar al cliente ${current.code}?`)) return;
    const removed = await run(() => api(`/api/clients/${encodeURIComponent(current.code)}`, { method: "DELETE" }));
    if (removed) setSelected(null);
  };

  const term = search.trim().toLowerCase();
  const visible = clients.filter(
    (c) =>
      (!onlyUnverified || c.location_status !== "verificada") &&
      (!term || c.code.toLowerCase().includes(term) || c.name.toLowerCase().includes(term)),
  );
  const unverifiedCount = clients.filter((c) => c.location_status !== "verificada").length;

  return (
    <section className="page clients-page">
      <div className="clients-side">
        <h1>Clientes</h1>
        <p className="hint">{unverifiedCount} de {clients.length} clientes aún no tienen su ubicación verificada.</p>
        <div className="capture">
          <label className="grow">
            Buscar
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Código o nombre" />
          </label>
          <label className="check">
            <input type="checkbox" checked={onlyUnverified} onChange={(e) => setOnlyUnverified(e.target.checked)} />
            Solo sin verificar
          </label>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
        <ul className="client-list">
          {visible.map((c) => (
            <li key={c.code}>
              <button type="button" aria-pressed={c.code === selected} onClick={() => setSelected(c.code)}>
                <span><strong>{c.code}</strong> <span className="muted">{c.name}</span></span>
                <span className={`status status-${c.location_status}`}>
                  {c.lat === null ? "Sin ubicación" : STATUS_LABEL[c.location_status]}
                </span>
              </button>
            </li>
          ))}
          {visible.length === 0 && <li className="empty">Ningún cliente coincide con la búsqueda.</li>}
        </ul>

        <form className="client-form" onSubmit={create}>
          <h2>Nuevo cliente</h2>
          <label>Código<input value={draft.code} onChange={(e) => setDraft({ ...draft, code: e.target.value })} required maxLength={40} /></label>
          <label>Nombre<input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} required maxLength={120} /></label>
          <label>Dirección<input value={draft.address} onChange={(e) => setDraft({ ...draft, address: e.target.value })} /></label>
          <fieldset className="window-field">
            <legend>Recibe de</legend>
            <input type="time" value={draft.opens_at} onChange={(e) => setDraft({ ...draft, opens_at: e.target.value })} required aria-label="Recibe desde" />
            <span aria-hidden="true">a</span>
            <input type="time" value={draft.closes_at} onChange={(e) => setDraft({ ...draft, closes_at: e.target.value })} required aria-label="Recibe hasta" />
          </fieldset>
          <button type="submit">Agregar cliente</button>
        </form>
      </div>

      <div className="clients-main">
        <p className="map-instruction" role="status">
          {current
            ? `Haz clic en el mapa o arrastra el punto para fijar la ubicación de ${current.code}.`
            : "Elige un cliente en la lista o en el mapa para fijar su ubicación."}
        </p>
        <div ref={container} className="map" />
        <ul className="map-legend">
          <li><span className="client-marker status-verificada static" /> Verificada</li>
          <li><span className="client-marker status-sintetica static" /> Sintética</li>
          <li><span className="client-marker status-pendiente static" /> Pendiente</li>
          <li><span className="depot-marker static" /> Bodega</li>
        </ul>
        {current && (
          <form className="client-form" onSubmit={saveEdit}>
            <h2>{current.code}</h2>
            <label>Nombre<input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} required maxLength={120} /></label>
            <label>Dirección<input value={edit.address} onChange={(e) => setEdit({ ...edit, address: e.target.value })} /></label>
            <fieldset className="window-field">
              <legend>Recibe de <span className="muted">(nunca se le entrega fuera de este horario)</span></legend>
              <input type="time" value={edit.opens_at} onChange={(e) => setEdit({ ...edit, opens_at: e.target.value })} required aria-label={`${current.code} recibe desde`} />
              <span aria-hidden="true">a</span>
              <input type="time" value={edit.closes_at} onChange={(e) => setEdit({ ...edit, closes_at: e.target.value })} required aria-label={`${current.code} recibe hasta`} />
            </fieldset>
            <fieldset className="truck-checks">
              <legend>Camiones que no pueden entrar <span className="muted">(por sus dimensiones)</span></legend>
              {fleet.map((v) => (
                <label key={v.vehicle_id} className="check">
                  <input
                    type="checkbox"
                    checked={edit.blocked_vehicles.includes(v.vehicle_id)}
                    onChange={(e) =>
                      setEdit({
                        ...edit,
                        blocked_vehicles: e.target.checked
                          ? [...edit.blocked_vehicles, v.vehicle_id]
                          : edit.blocked_vehicles.filter((id) => id !== v.vehicle_id),
                      })
                    }
                  />
                  {v.vehicle_id} <span className="muted">({(v.capacity_kg / 1000).toLocaleString("es-MX")} t)</span>
                </label>
              ))}
              {fleet.length > 0 && edit.blocked_vehicles.length === fleet.length && (
                <p className="error">Ningún camión podría entrar: sus pedidos pasarían a otro día.</p>
              )}
            </fieldset>
            <label className="check">
              <input type="checkbox" checked={edit.puesta} onChange={(e) => setEdit({ ...edit, puesta: e.target.checked })} />
              <span>
                Puesta <span className="muted">(en urgencia acepta solo 10–15% de su pedido; el resto pasa a otro día)</span>
              </span>
            </label>
            <div className="actions">
              <button type="submit">Guardar cambios</button>
              <button type="button" className="link danger" onClick={remove}>Borrar cliente</button>
            </div>
          </form>
        )}
      </div>
    </section>
  );
}
