import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, setOnUnauthorized } from "./api";
import { hhmm, kg, mxn, tomorrowISO } from "./format";
import { segments, tripLabel } from "./timeline";

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
  it("sin red da un mensaje legible", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("failed"); }));
    await expect(api("/api/me")).rejects.toEqual(new ApiError(0, "no hay conexión con el servidor"));
  });
});
