export type Client = {
  code: string;
  name: string;
  address: string;
  lat: number | null;
  lon: number | null;
  location_status: "sintetica" | "pendiente" | "verificada";
};

export type Vehicle = {
  vehicle_id: string;
  capacity_kg: number;
  km_per_liter: number;
  available: boolean;
  fixed_dispatch_cost_mxn: number;
};

export type Params = {
  diesel_mxn_per_liter: number;
  loading_mxn_per_kg: number;
  shift_minutes: number;
  service_minutes: number;
  reload_minutes: number;
  max_trips_per_vehicle: number;
  time_limit_s: number;
};

/** trip_no null: solo el camión, el plan elige viaje y orden. position: orden fijado a mano. */
export type Lock = { vehicle_id: string; trip_no: number | null; position: number | null };

export type Order = {
  id: number;
  date: string;
  client_code: string;
  client_name: string;
  kg: number;
  lock: Lock | null;
};

export type Stop = {
  order_id: string;
  client_code: string;
  client_name: string;
  kg: number;
  arrival_min: number;
  departure_min: number;
};

export type Trip = {
  trip_no: number;
  start_min: number;
  end_min: number;
  km: number;
  kg: number;
  capacity_pct: number;
  geometry: number[][];
  stops: Stop[];
};

export type VehiclePlan = { vehicle_id: string; capacity_kg: number; trips: Trip[] };

export type Unserved = {
  order_id: string;
  client_code: string;
  client_name: string;
  kg: number;
  reason: string;
  reason_label: string;
};

export type Plan = {
  shift_start: string;
  summary: {
    cost_mxn: number;
    km_total: number;
    liters_total: number;
    reloads: number;
    vehicles_used: number;
    served_kg: number;
    unserved_kg: number;
  };
  uses_unverified_locations: boolean;
  unverified_clients: string[];
  afternoon_load: { vehicle_id: string; kg: number; orders: number; capacity_pct: number }[];
  vehicles: VehiclePlan[];
  unserved: Unserved[];
  baseline: { cost_mxn: number; served_kg: number };
  comparison: { served_kg_diff: number; cost_diff_mxn: number; optimized_is_better_or_equal: boolean };
  lock_cost_diff_mxn: number | null;
};

export type PlanStatus = {
  status: "ninguno" | "calculando" | "listo" | "error";
  stale: boolean;
  error: string | null;
  plan: Plan | null;
  computed_at: string | null;
};

export type Config = {
  depot: { lat: number; lon: number };
  provider: string;
  bounds: [number, number, number, number];
};
