import type { ReactNode } from "react";
import { Bell, Droplets, Fish, LayoutDashboard, LogOut, RefreshCw, ScanEye, TrendingUp, Waves, type LucideIcon } from "lucide-react";
import type { AuthUser } from "../types";

export type LegacyPage = "overview" | "monitoring" | "sensors" | "water" | "alerts" | "predictions" | "behavior";

export const LEGACY_PAGES: { id: LegacyPage; label: string; title: string; icon: LucideIcon }[] = [
  { id: "overview", label: "Overview", title: "Farm Overview", icon: LayoutDashboard },
  { id: "monitoring", label: "Monitoring", title: "Live Fish Monitoring", icon: ScanEye },
  { id: "sensors", label: "Sensors", title: "Live Sensors", icon: Waves },
  { id: "water", label: "Water", title: "Water Quality & Assessment", icon: Droplets },
  { id: "alerts", label: "Alerts", title: "Alerts & SMS Setup", icon: Bell },
  { id: "predictions", label: "Forecasts", title: "Predictions & Forecast", icon: TrendingUp },
  { id: "behavior", label: "Behavior", title: "Fish Behavior Analysis", icon: Fish },
];

export type LegacyTone = "ok" | "warn" | "bad" | "mute";
export interface LegacyStatusItem { label: string; value: string; tone: LegacyTone }
const DOT: Record<LegacyTone, string> = { ok: "bg-brand", warn: "bg-warn", bad: "bg-bad", mute: "bg-slate-300" };

export default function ShellLegacy({ page, setPage, status, fetchedAt, lastReadingAt, pollSeconds, canRefresh, busy, onRefresh, user, onLogout, children }: {
  page: LegacyPage; setPage: (p: LegacyPage) => void; status: LegacyStatusItem[]; fetchedAt: number | null; lastReadingAt: number | null; pollSeconds: number;
  canRefresh: boolean; busy: boolean; onRefresh: () => void; user: AuthUser; onLogout: () => void; children: ReactNode;
}) {
  const title = LEGACY_PAGES.find((p) => p.id === page)!.title;
  const hms = (t: number) => new Date(t).toLocaleTimeString([], { hour12: false });
  const phone = user.phone ? `${user.phone.slice(0, 3)}••••${user.phone.slice(-3)}` : "Signed in";
  const nav = (mobile: boolean) => LEGACY_PAGES.map(({ id, label, icon: Icon }) => (
    <button key={id} onClick={() => setPage(id)} aria-current={page === id ? "page" : undefined}
      className={mobile
        ? `flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] ${page === id ? "font-semibold text-brand" : "text-mute"}`
        : `flex w-full items-center gap-2.5 rounded-full px-4 py-2.5 text-sm transition-colors ${page === id ? "bg-brand font-medium text-white shadow-sm" : "text-mute hover:bg-surface hover:text-ink"}`}>
      <Icon className={mobile ? "h-4 w-4" : "h-4 w-4"} />{label}
    </button>
  ));

  return (
    <div className="min-h-screen lg:pl-56">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-56 flex-col border-r border-line bg-white p-4 lg:flex" aria-label="Primary">
        <div className="mb-6 flex items-center gap-2.5 px-1">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-brand/15"><Fish className="h-5 w-5 text-brand" /></span>
          <span className="text-[15px] font-semibold text-ink">Aquaculture<span className="text-brand">AI</span></span>
        </div>
        <nav className="space-y-1.5" aria-label="Pages">{nav(false)}</nav>
        <div className="mt-auto space-y-3 border-t border-line pt-3 text-xs">
          <div>
            <p className="truncate font-medium text-ink">{user.name || "Farmer"}</p>
            <p className="text-[11px] text-mute">{phone}</p>
            <button onClick={onLogout} className="mt-1 inline-flex items-center gap-1 text-[11px] font-medium text-cyan hover:underline">
              <LogOut className="h-3 w-3" />Log out
            </button>
          </div>
          <div className="space-y-1.5" aria-label="Integration status">
            <p className="mb-1 text-[10px] uppercase tracking-wide text-mute">Integrations</p>
            {status.map((s) => (
              <p key={s.label} className="flex items-center justify-between gap-2 text-mute">
                <span>{s.label}</span><span className="flex items-center gap-1.5 text-ink"><span className={`h-2 w-2 rounded-full ${DOT[s.tone]}`} />{s.value}</span>
              </p>
            ))}
          </div>
        </div>
      </aside>

      <header className="flex flex-wrap items-center gap-3 px-4 pb-2 pt-5 lg:px-6">
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand/15 lg:hidden"><Fish className="h-4 w-4 text-brand" /></span>
        <h1 className="text-2xl font-extrabold tracking-tight text-ink sm:text-[28px]">{title}</h1>
        <div className="ml-auto flex flex-wrap items-center gap-2 text-xs text-mute">
          <button onClick={onLogout} className="inline-flex h-9 items-center gap-1.5 rounded-full border border-line bg-white px-3 text-ink lg:hidden" aria-label="Log out">
            <LogOut className="h-3.5 w-3.5" /><span className="hidden sm:inline">Log out</span>
          </button>
          {canRefresh && (
            <span className="rounded-full bg-brand/10 px-3 py-1.5 font-medium text-brand">{`Live updates on · checking every ${pollSeconds} s`}</span>
          )}
          <span className="hidden sm:inline" title="Updated = last successful ThingSpeak request. Last reading = timestamp of the newest valid measurement.">
            {fetchedAt ? <>Updated <b className="font-semibold text-ink">{hms(fetchedAt)}</b>{lastReadingAt ? <> {"·"} last reading <b className="font-semibold text-ink">{hms(lastReadingAt)}</b></> : null}</> : "No successful fetch yet"}
          </span>
          <button onClick={onRefresh} disabled={!canRefresh || busy} aria-label="Refresh sensor data"
            className="inline-flex h-10 items-center gap-1.5 rounded-full bg-brand px-4 text-sm font-medium text-white shadow-sm hover:opacity-90 disabled:opacity-40">
            <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} /><span>Refresh</span>
          </button>
        </div>
      </header>

      <main className="px-4 pb-24 pt-2 lg:px-6 lg:pb-8">{children}</main>
      <nav className="fixed inset-x-0 bottom-0 z-30 flex border-t border-line bg-white lg:hidden" aria-label="Pages (mobile)">{nav(true)}</nav>
    </div>
  );
}
