import maplibregl, { Map as MapLibre, Marker, StyleSpecification } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { hhmm, kg, tripColor, type ColorOf } from "../format";
import type { Client, Config, VehiclePlan } from "../types";

const STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";
const NO_TILES: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "fondo", type: "background", paint: { "background-color": "#DDE3E6" } }],
};

/** Sin acceso a las teselas, el mapa sigue funcionando sobre un fondo liso. */
export async function createMap(container: HTMLElement, center: Config["depot"]): Promise<MapLibre> {
  let style: string | StyleSpecification = NO_TILES;
  try {
    const response = await fetch(STYLE_URL);
    if (response.ok) style = STYLE_URL;
  } catch {
    // se queda el fondo liso
  }
  const map = new maplibregl.Map({ container, style, center: [center.lon, center.lat], zoom: 10.5 });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }));
  return map;
}

type Props = {
  vehicles: VehiclePlan[];
  clients: Client[];
  depot: Config["depot"];
  colorOf: ColorOf;
  only: string | null;
};

export function RouteMap({ vehicles, clients, depot, colorOf, only }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MapLibre | null>(null);
  const drawn = useRef<{ layers: string[]; markers: Marker[] }>({ layers: [], markers: [] });

  useEffect(() => {
    let cancelled = false;
    let created: MapLibre | null = null;
    void createMap(container.current!, depot).then((m) => {
      if (cancelled) return m.remove();
      created = m;
      m.on("load", () => setMap(m));
    });
    return () => {
      cancelled = true;
      drawn.current = { layers: [], markers: [] };
      created?.remove();
    };
  }, [depot]);

  useEffect(() => {
    if (!map) return;
    drawn.current.markers.forEach((m) => m.remove());
    drawn.current.layers.forEach((id) => {
      map.removeLayer(id);
      map.removeSource(id);
    });
    const layers: string[] = [];
    const markers: Marker[] = [];
    const bounds = new maplibregl.LngLatBounds([depot.lon, depot.lat], [depot.lon, depot.lat]);
    const where = new Map(clients.map((c) => [c.code, c]));

    for (const vehicle of vehicles) {
      if (only && vehicle.vehicle_id !== only) continue;
      const truck = colorOf(vehicle.vehicle_id);
      for (const trip of vehicle.trips) {
        const color = tripColor(truck, trip.trip_no);
        if (trip.geometry.length > 1) {
          const id = `ruta-${vehicle.vehicle_id}-${trip.trip_no}`;
          map.addSource(id, {
            type: "geojson",
            data: { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: trip.geometry } },
          });
          map.addLayer({
            id,
            type: "line",
            source: id,
            layout: { "line-cap": "round", "line-join": "round" },
            paint: {
              "line-color": color,
              "line-width": 4,
              "line-opacity": 0.9,
              ...(trip.trip_no > 1 ? { "line-dasharray": [1.5, 1.5] } : {}),
            },
          });
          layers.push(id);
          trip.geometry.forEach(([lon, lat]) => bounds.extend([lon, lat]));
        }
        trip.stops.forEach((stop, i) => {
          const client = where.get(stop.client_code);
          if (client?.lat == null || client.lon == null) return;
          const el = document.createElement("div");
          el.className = "stop-marker";
          el.style.background = color;
          el.textContent = String(i + 1);
          const popup = new maplibregl.Popup({ offset: 14, closeButton: false }).setText(
            `${stop.client_code}, ${stop.client_name}. ${vehicle.vehicle_id} viaje ${trip.trip_no}, parada ${i + 1}. Llega ${hhmm(stop.arrival_min)}, ${kg(stop.kg)}.`,
          );
          markers.push(new maplibregl.Marker({ element: el }).setLngLat([client.lon, client.lat]).setPopup(popup).addTo(map));
          bounds.extend([client.lon, client.lat]);
        });
      }
    }
    const el = document.createElement("div");
    el.className = "depot-marker";
    el.title = "Bodega";
    markers.push(new maplibregl.Marker({ element: el }).setLngLat([depot.lon, depot.lat]).addTo(map));

    drawn.current = { layers, markers };
    map.fitBounds(bounds, { padding: 48, duration: 300, maxZoom: 14 });
  }, [map, vehicles, clients, depot, colorOf, only]);

  return <div ref={container} className="map" role="img" aria-label="Mapa de las rutas de cada camión" />;
}
