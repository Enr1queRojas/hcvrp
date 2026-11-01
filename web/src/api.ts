export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

let onUnauthorized: () => void = () => {};

export function setOnUnauthorized(fn: () => void): void {
  onUnauthorized = fn;
}

export async function api<T = void>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: options.method ?? "GET",
      headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch {
    throw new ApiError(0, "no hay conexión con el servidor");
  }
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401) onUnauthorized();
    throw new ApiError(response.status, data?.detail ?? `el servidor respondió ${response.status}`);
  }
  return data as T;
}

export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "ocurrió un error inesperado";
}
