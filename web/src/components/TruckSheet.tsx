import { useEffect } from "react";
import { createPortal } from "react-dom";
import logo from "../assets/logo-graneros-guerra.png";
import { hhmm, kg, km, windowText } from "../format";
import type { Client, VehiclePlan } from "../types";

type Props = { date: string; vehicle: VehiclePlan; clients: Client[]; onDone: () => void };

/** Hoja para el chofer: se imprime sola y solo ella. */
export function TruckSheet({ date, vehicle, clients, onDone }: Props) {
  useEffect(() => {
    window.addEventListener("afterprint", onDone);
    const timer = setTimeout(() => window.print(), 50);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("afterprint", onDone);
    };
  }, [onDone]);

  const address = (code: string) => clients.find((c) => c.code === code)?.address ?? "";

  return createPortal(
    <article className="print-sheet">
      <img src={logo} alt="Graneros Guerra" width={120} height={84} />
      <h1>Camión {vehicle.vehicle_id}</h1>
      <p>Reparto del {date}. Salida a las 09:00 con el viaje 1 ya cargado.</p>
      {vehicle.trips.map((trip) => (
        <section key={trip.trip_no}>
          <h2>Viaje {trip.trip_no}: sale {hhmm(trip.start_min)}, regresa {hhmm(trip.end_min)}</h2>
          <p>{kg(trip.kg)}, {km(trip.km)}</p>
          <table>
            <thead>
              <tr>
                <th>Parada</th>
                <th>Cliente</th>
                <th>Dirección</th>
                <th className="num">Kilos</th>
                <th>Horario</th>
                <th>Llega</th>
                <th>Sale</th>
              </tr>
            </thead>
            <tbody>
              {trip.stops.map((stop, i) => (
                <tr key={stop.order_id}>
                  <td>{i + 1}</td>
                  <td>{stop.client_code} {stop.client_name}</td>
                  <td>{address(stop.client_code)}</td>
                  <td className="num">{kg(stop.kg)}</td>
                  <td>{windowText(stop.window_start, stop.window_end)}</td>
                  <td>
                    {hhmm(stop.arrival_min)}
                    {stop.late_min > 0 && <strong> ({stop.late_min} min tarde)</strong>}
                  </td>
                  <td>{hhmm(stop.departure_min)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </article>,
    document.body,
  );
}
