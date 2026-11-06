/** Orden de entrega de un camión: ids de pedido por viaje, en el orden en que se entregan. */
export type Trips = string[][];

function locate(trips: Trips, id: string): [number, number] | null {
  for (let t = 0; t < trips.length; t++) {
    const i = trips[t].indexOf(id);
    if (i >= 0) return [t, i];
  }
  return null;
}

const compact = (trips: Trips): Trips => trips.filter((t) => t.length > 0);

/** Mueve `id` justo antes (o después) de `target`; puede pasar a otro viaje del mismo camión. */
export function moveStop(trips: Trips, id: string, target: string, after: boolean): Trips {
  if (id === target || !locate(trips, id) || !locate(trips, target)) return trips;
  const without = trips.map((t) => t.filter((x) => x !== id));
  const [t, i] = locate(without, target)!;
  without[t].splice(after ? i + 1 : i, 0, id);
  return compact(without);
}

/**
 * Sube (-1) o baja (+1) una parada. En el borde de un viaje pasa al final del viaje anterior
 * o al principio del siguiente.
 */
export function shiftStop(trips: Trips, id: string, delta: -1 | 1): Trips {
  const at = locate(trips, id);
  if (!at) return trips;
  const [t, i] = at;
  const next = trips.map((trip) => [...trip]);
  const j = i + delta;
  if (j >= 0 && j < next[t].length) {
    [next[t][i], next[t][j]] = [next[t][j], next[t][i]];
    return next;
  }
  const other = t + delta;
  if (other < 0 || other >= next.length) return trips;
  next[t].splice(i, 1);
  if (delta < 0) next[other].push(id);
  else next[other].unshift(id);
  return compact(next);
}
