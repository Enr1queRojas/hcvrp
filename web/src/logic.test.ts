import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, apiUrl, setOnUnauthorized } from "./api";
import { clockToMinute, hhmm, kg, lockText, minuteToClock, mxn, tomorrowISO, tripColor, truckColors, windowText } from "./format";
import { moveStop, shiftStop } from "./sequence";
import { segments, tripLabel } from "./timeline";

describe("orden de paradas", () => {
  const trips = [["a", "b", "c"], ["d", "e"]];
  it("mueve una parada antes o después de otra", () => {
    expect(moveStop(trips, "c", "a", false)).toEqual([["c", "a", "b"], ["d", "e"]]);
    expect(moveStop(trips, "a", "b", true)).toEqual([["b", "a", "c"], ["d", "e"]]);
  });
  it("pasa una parada a otro viaje y quita viajes vacíos", () => {
    expect(moveStop(trips, "b", "e", true)).toEqual([["a", "c"], ["d", "e", "b"]]);
    expect(moveStop([["a"], ["b"]], "a", "b", false)).toEqual([["a", "b"]]);
  });
  it("no cambia nada al soltar sobre sí misma", () => {
    expect(moveStop(trips, "b", "b", true)).toBe(trips);
  });
  it("sube y baja con el teclado, cruzando entre viajes", () => {
    expect(shiftStop(trips, "b", -1)).toEqual([["b", "a", "c"], ["d", "e"]]);
    expect(shiftStop(trips, "c", 1)).toEqual([["a", "b"], ["c", "d", "e"]]);
    expect(shiftStop(trips, "d", -1)).toEqual([["a", "b", "c", "d"], ["e"]]);
    expect(shiftStop(trips, "a", -1)).toBe(trips);
    expect(shiftStop(trips, "e", 1)).toBe(trips);
  });
  it("describe el bloqueo", () => {
    expect(lockText({ vehicle_id: "Leña", trip_no: null, position: null })).toBe("Fijado en Leña");
    expect(lockText({ vehicle_id: "Leña", trip_no: 2, position: 3 })).toBe("Fijado en Leña, viaje 2, parada 3");
  });
});

describe("horarios de entrega", () => {
  it("convierte la hora del reloj a minutos desde las 09:00 y de regreso", () => {
    expect(clockToMinute("10:30")).toBe(90);
    expect(clockToMinute("09:00")).toBe(0);
    expect(clockToMinute("")).toBeNull();
    expect(clockToMinute("08:59")).toBeNaN();
    expect(minuteToClock(90)).toBe("10:30");
    expect(minuteToClock(null)).toBe("");
  });
  it("describe el horario", () => {
    expect(windowText(60, 180)).toBe("10:00 a 12:00");
    expect(windowText(null, 120)).toBe("antes de las 11:00");
    expect(windowText(240, null)).toBe("desde las 13:00");
    expect(windowText(null, null)).toBe("");
  });
});

describe("colores", () => {
  it("da un color distinto a cada camión de la flota", () => {
    const ids = ["Leña", "Soriano", "Corto", "Guinda", "Volvo", "Mercedes"];
    const colorOf = truckColors(ids);
    expect(new Set(ids.map(colorOf)).size).toBe(ids.length);
    expect(colorOf("Desconocido")).toBe(colorOf("Desconocido"));
  });
  it("da un tono distinto a cada viaje del mismo camión", () => {
    const base = truckColors(["Leña"])("Leña");
    const shades = [1, 2, 3, 4].map((n) => tripColor(base, n));
    expect(shades[0]).toBe(base);
    expect(new Set(shades).size).toBe(4);
  });
});

describe("format", () => {
  it("convierte minutos de jornada en hora del día", () => {
    expect(hhmm(0)).toBe("09:00");
    expect(hhmm(65)).toBe("10:05");
    expect(hhmm(480)).toBe("17:00");
  });
  it("da formato a dinero y kilos", () => {
    expect(mxn(13772.6)).toBe("$13,772.60");
    expect(mxn(-677.86)).toBe("-$677.86");
    expect(kg(120000)).toBe("120,000 kg");
  });
  it("calcula mañana con cambio de año", () => {
    expect(tomorrowISO(new Date(2026, 11, 31))).toBe("2027-01-01");
    expect(tomorrowISO(new Date(2026, 10, 1))).toBe("2026-11-02");
  });
});

describe("segments", () => {
  const trip = (trip_no: number, start_min: number, end_min: number) => ({ trip_no, start_min, end_min });

  it("pone una recarga entre dos viajes", () => {
    expect(segments([trip(1, 0, 100), trip(2, 220, 300)], 120)).toEqual([
      { kind: "trip", start: 0, end: 100, tripNo: 1 },
      { kind: "reload", start: 100, end: 220 },
      { kind: "trip", start: 220, end: 300, tripNo: 2 },
    ]);
  });
  it("con un solo viaje no hay recarga", () => {
    expect(segments([trip(1, 0, 100)], 120)).toEqual([{ kind: "trip", start: 0, end: 100, tripNo: 1 }]);
  });
});

describe("tripLabel", () => {
  it("usa singular y plural", () => {
    expect(tripLabel(1, 1, 200)).toBe("Viaje 1: 1 cliente");
    expect(tripLabel(2, 7, 200)).toBe("Viaje 2: 7 clientes");
  });
  it("se acorta en los viajes breves para no cortarse", () => {
    expect(tripLabel(2, 4, 100)).toBe("Viaje 2");
    expect(tripLabel(3, 1, 30)).toBe("3");
  });
});

describe("api", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    setOnUnauthorized(() => {});
  });
  const respond = (status: number, body: unknown) =>
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status })));

  it("lanza el mensaje de detail", async () => {
    respond(422, { detail: "los kg deben ser un número entero" });
    await expect(api("/api/orders")).rejects.toEqual(new ApiError(422, "los kg deben ser un número entero"));
  });
  it("avisa cuando la sesión venció", async () => {
    respond(401, { detail: "inicia sesión" });
    const onUnauthorized = vi.fn();
    setOnUnauthorized(onUnauthorized);
    await expect(api("/api/me")).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });
  it("una respuesta 204 no es error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));
    await expect(api("/api/orders/1", { method: "DELETE" })).resolves.toBeUndefined();
  });
  it("pide la API relativa a la página, para servir bajo /rutas/", async () => {
    expect(apiUrl("/api/me")).toBe("api/me");
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({}), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await api("/api/me");
    expect(fetchMock).toHaveBeenCalledWith("api/me", expect.anything());
  });
  it("sin red da un mensaje legible", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("failed"); }));
    await expect(api("/api/me")).rejects.toEqual(new ApiError(0, "no hay conexión con el servidor"));
  });
});
