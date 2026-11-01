const MONEY = new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN" });
const NUMBER = new Intl.NumberFormat("es-MX");

const TRUCK_COLORS: Record<string, string> = {
  V1: "#0E7C86",
  V2: "#B26A00",
  V3: "#6D3FA8",
  V4: "#C2324E",
};

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

export function truckColor(vehicleId: string): string {
  return TRUCK_COLORS[vehicleId] ?? "#3F6B3A";
}
