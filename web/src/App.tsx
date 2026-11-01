import { useCallback, useEffect, useRef, useState } from "react";
import { api, setOnUnauthorized } from "./api";
import logo from "./assets/logo-graneros-guerra.png";
import { tomorrowISO } from "./format";
import { Clients } from "./screens/Clients";
import { Fleet } from "./screens/Fleet";
import { Login } from "./screens/Login";
import { Orders } from "./screens/Orders";
import { PlanView } from "./screens/PlanView";
import type { Config, PlanStatus } from "./types";

const PAGES = [
  ["pedidos", "Pedidos"],
  ["plan", "Plan"],
  ["clientes", "Clientes"],
  ["flota", "Flota y parámetros"],
] as const;

type Page = (typeof PAGES)[number][0];

function pageFromHash(): Page {
  const hash = window.location.hash.slice(1);
  return PAGES.some(([id]) => id === hash) ? (hash as Page) : "pedidos";
}

function usePlanStatus(date: string, enabled: boolean) {
  const [status, setStatus] = useState<PlanStatus | null>(null);
  const currentDate = useRef(date);
  currentDate.current = date;

  const refresh = useCallback(async () => {
    try {
      const next = await api<PlanStatus>(`/api/plan?date=${date}`);
      if (currentDate.current === date) setStatus(next);
    } catch {
      // Sin red se reintenta en el siguiente ciclo; una sesión vencida ya vuelve al login.
    }
  }, [date]);

  useEffect(() => {
    if (!enabled) return;
    setStatus(null);
    void refresh();
  }, [enabled, refresh]);

  const busy = status?.status === "calculando";
  useEffect(() => {
    if (!enabled) return;
    const timer = setInterval(refresh, busy ? 1500 : 6000);
    return () => clearInterval(timer);
  }, [enabled, busy, refresh]);

  return { status, refresh };
}

function statusText(status: PlanStatus | null): string {
  switch (status?.status) {
    case "calculando":
      return "Calculando el plan";
    case "listo":
      return status.stale ? "Sin pedidos para este día" : "Plan al día";
    case "error":
      return "El plan tiene un problema";
    case "ninguno":
      return "Sin pedidos para este día";
    default:
      return "";
  }
}

export function App() {
  const [user, setUser] = useState<string | null | undefined>(undefined);
  const [page, setPage] = useState<Page>(pageFromHash);
  const [date, setDate] = useState(() => tomorrowISO(new Date()));
  const [config, setConfig] = useState<Config | null>(null);
  const { status, refresh } = usePlanStatus(date, Boolean(user));

  useEffect(() => {
    setOnUnauthorized(() => setUser(null));
    api<{ username: string }>("/api/me")
      .then((me) => setUser(me.username))
      .catch(() => setUser(null));
  }, []);

  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    if (user) void api<Config>("/api/config").then(setConfig).catch(() => {});
  }, [user]);

  if (user === undefined) return null;
  if (user === null) return <Login onLogin={setUser} />;

  const logout = async () => {
    await api("/api/logout", { method: "POST" }).catch(() => {});
    setUser(null);
  };

  return (
    <>
      <header className="topbar">
        <a className="brand" href="#pedidos">
          <span className="brand-plate">
            <img src={logo} alt="Graneros Guerra" width={80} height={56} />
          </span>
          Reparto
        </a>
        <label className="date-field">
          Reparto del
          <input
            type="date"
            value={date}
            onChange={(e) => e.target.value && setDate(e.target.value)}
          />
        </label>
        <nav aria-label="Secciones">
          {PAGES.map(([id, label]) => (
            <a key={id} href={`#${id}`} aria-current={page === id ? "page" : undefined}>
              {label}
            </a>
          ))}
        </nav>
        <span className={`plan-state plan-state-${status?.status ?? "none"}`} role="status">
          {statusText(status)}
        </span>
        <span className="user">
          {user}
          <button type="button" className="link" onClick={logout}>
            Salir
          </button>
        </span>
      </header>
      <main>
        {page === "pedidos" && <Orders date={date} onChanged={refresh} />}
        {page === "plan" && config && (
          <PlanView date={date} status={status} config={config} onChanged={refresh} />
        )}
        {page === "clientes" && config && <Clients config={config} onChanged={refresh} />}
        {page === "flota" && <Fleet onChanged={refresh} />}
      </main>
    </>
  );
}
