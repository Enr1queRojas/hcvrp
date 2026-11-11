const MONEY = new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN" });
const NUMBER = new Intl.NumberFormat("es-MX");

/** Tonos bien separados entre sí y lo bastante oscuros para llevar texto blanco encima. */
const TRUCK_PALETTE = [
  "#0E7C86", // verde azulado
  "#B26A00", // ámbar
  "#6D3FA8", // morado
  "#C2324E", // carmín
  "#2F6FB5", // azul
  "#3F7D20", // verde
  "#A63D99", // magenta
  "#8A5A2B", // café
  "#1F4E79", // azul marino
  "#6B6B00", // oliva
];

export function hhmm(minute: number): string {
  const total = 9 * 60 + minute;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(Math.floor(total / 60))}:${pad(total % 60)}`;
}

export function mxn(value: number): string {
  return MONEY.format(value);
}

export function kg(value: number): string {
  return `${NUMBER.format(value)} kg`;
}

export function km(value: number): string {
  return `${value.toFixed(1)} km`;
}

export function tomorrowISO(now: Date): string {
  const next = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${next.getFullYear()}-${pad(next.getMonth() + 1)}-${pad(next.getDate())}`;
}

export type ColorOf = (vehicleId: string) => string;

/**
 * Asigna a cada camión un color según su lugar en la flota, para que dos camiones
 * nunca compartan color (mientras la flota no supere la paleta). Un camión que no
 * esté en la lista recibe un color estable derivado de su nombre.
 */
export function truckColors(vehicleIds: string[]): ColorOf {
  const assigned = new Map(vehicleIds.map((id, i) => [id, TRUCK_PALETTE[i % TRUCK_PALETTE.length]]));
  return (vehicleId) => {
    const known = assigned.get(vehicleId);
    if (known) return known;
    let hash = 0;
    for (const ch of vehicleId) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
    return TRUCK_PALETTE[hash % TRUCK_PALETTE.length];
  };
}

function mix(hex: string, toward: number, amount: number): string {
  const n = parseInt(hex.slice(1), 16);
  const channel = (shift: number) => {
    const c = (n >> shift) & 255;
    return Math.round(c + (toward - c) * amount);
  };
  return `#${[16, 8, 0].map((s) => channel(s).toString(16).padStart(2, "0")).join("")}`;
}

/** Cada viaje de un mismo camión lleva un tono distinto de su color: el 1 tal cual, luego más oscuro, luego más claro. */
export function tripColor(base: string, tripNo: number): string {
  const step = (tripNo - 1) % 4;
  if (step === 0) return base;
  if (step === 1) return mix(base, 0, 0.35);
  if (step === 2) return mix(base, 255, 0.25);
  return mix(base, 0, 0.6);
}

export function lockText(lock: { vehicle_id: string; trip_no: number | null; position: number | null }): string {
  if (lock.trip_no === null) return `Fijado en ${lock.vehicle_id}`;
  const base = `Fijado en ${lock.vehicle_id}, viaje ${lock.trip_no}`;
  return lock.position === null ? base : `${base}, parada ${lock.position}`;
}

const SHIFT_START = 9 * 60;

/** "HH:MM" del reloj a minutos desde las 09:00. Vacío: null. Antes de las 09:00: NaN. */
export function clockToMinute(value: string): number | null {
  if (!value) return null;
  const [h, m] = value.split(":").map(Number);
  const minute = h * 60 + m - SHIFT_START;
  return minute < 0 || Number.isNaN(minute) ? NaN : minute;
}

/** Minutos desde las 09:00 a "HH:MM" para un <input type="time">; null: "". */
export function minuteToClock(minute: number | null): string {
  return minute === null ? "" : hhmm(minute);
}

export function windowText(start: number | null, end: number | null): string {
  if (start !== null && end !== null) return `${hhmm(start)} a ${hhmm(end)}`;
  if (end !== null) return `antes de las ${hhmm(end)}`;
  if (start !== null) return `desde las ${hhmm(start)}`;
  return "";
}

/**
 * El código del cliente que el usuario quiso escribir: acepta el código o el nombre exacto, sin
 * importar mayúsculas. Si no coincide con ninguno, devuelve lo escrito tal cual.
 */
export function resolveClientCode(typed: string, clients: { code: string; name: string }[]): string {
  const text = typed.trim();
  const lower = text.toLowerCase();
  const match =
    clients.find((c) => c.code === text) ??
    clients.find((c) => c.code.toLowerCase() === lower) ??
    clients.find((c) => c.name.toLowerCase() === lower);
  return match ? match.code : text;
}
