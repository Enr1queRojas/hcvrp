import { hhmm, kg, tripColor, type ColorOf } from "../format";
import { segments, tripLabel } from "../timeline";
import type { Params, Vehicle, VehiclePlan } from "../types";

type Props = {
  fleet: Vehicle[];
  vehicles: VehiclePlan[];
  params: Params;
  colorOf: ColorOf;
  only: string | null;
  onSelect: (vehicleId: string | null) => void;
};

export function ShiftTimeline({ fleet, vehicles, params, colorOf, only, onSelect }: Props) {
  const shift = params.shift_minutes;
  const pct = (minute: number) => `${(100 * minute) / shift}%`;
  const hours = Array.from({ length: Math.floor(shift / 60) + 1 }, (_, i) => i * 60);

  return (
    <div className="timeline">
      <div className="timeline-scale" aria-hidden="true">
        {hours.map((minute) => (
          <span key={minute} style={{ left: pct(minute) }}>{hhmm(minute)}</span>
        ))}
      </div>
      {fleet.map((truck) => {
        const plan = vehicles.find((v) => v.vehicle_id === truck.vehicle_id);
        const color = colorOf(truck.vehicle_id);
        const trips = plan?.trips ?? [];
        const lastTrip = trips[trips.length - 1];
        const note = !truck.available
          ? "No disponible"
          : lastTrip
            ? `Regresa ${hhmm(lastTrip.end_min)}`
            : "Sin salida";
        return (
          <div className="lane" key={truck.vehicle_id} data-dimmed={Boolean(only && only !== truck.vehicle_id)}>
            <button
              type="button"
              className="lane-label"
              style={{ borderColor: color }}
              aria-pressed={only === truck.vehicle_id}
              disabled={!plan}
              onClick={() => onSelect(only === truck.vehicle_id ? null : truck.vehicle_id)}
            >
              <strong>{truck.vehicle_id}</strong>
              <span>{note}</span>
            </button>
            <div className="lane-track">
              {hours.map((minute) => (
                <i key={minute} className="hour-mark" style={{ left: pct(minute) }} />
              ))}
              {segments(trips, params.reload_minutes).map((seg) => {
                const style = { left: pct(seg.start), width: pct(seg.end - seg.start) };
                if (seg.kind === "reload") {
                  return (
                    <div
                      key={`r${seg.start}`}
                      className="segment reload"
                      style={style}
                      title={`Recarga en bodega, ${hhmm(seg.start)} a ${hhmm(seg.end)}`}
                    >
                      {seg.end - seg.start >= 60 && <span>Recarga</span>}
                    </div>
                  );
                }
                const trip = trips.find((t) => t.trip_no === seg.tripNo)!;
                return (
                  <div
                    key={`t${seg.tripNo}`}
                    className="segment trip"
                    style={{ ...style, background: tripColor(color, trip.trip_no) }}
                    title={`Viaje ${trip.trip_no}, ${hhmm(seg.start)} a ${hhmm(seg.end)}: ${trip.stops.length} ${trip.stops.length === 1 ? "cliente" : "clientes"}, ${kg(trip.kg)}`}
                  >
                    <span>{tripLabel(trip.trip_no, trip.stops.length, seg.end - seg.start)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
