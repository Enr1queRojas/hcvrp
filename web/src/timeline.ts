export type Segment =
  | { kind: "trip"; start: number; end: number; tripNo: number }
  | { kind: "reload"; start: number; end: number };

type TripTimes = { trip_no: number; start_min: number; end_min: number };

export function tripLabel(tripNo: number, stops: number, minutes: number): string {
  if (minutes < 45) return String(tripNo);
  if (minutes < 150) return `Viaje ${tripNo}`;
  return `Viaje ${tripNo}: ${stops} ${stops === 1 ? "cliente" : "clientes"}`;
}

export function segments(trips: TripTimes[], reloadMinutes: number): Segment[] {
  const out: Segment[] = [];
  trips.forEach((trip, i) => {
    if (i > 0) out.push({ kind: "reload", start: trip.start_min - reloadMinutes, end: trip.start_min });
    out.push({ kind: "trip", start: trip.start_min, end: trip.end_min, tripNo: trip.trip_no });
  });
  return out;
}
