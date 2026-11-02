import { useCallback, useEffect, useState } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { RefreshCw, TriangleAlert } from "lucide-react";
import type { BehaviorStatsData } from "../types";
import { backendConfigured, getBehaviorStats } from "../services/api";
import { Badge, Panel } from "../components/ui";

const REFRESH_MS = 5000;
const fmt = (v: number | null | undefined, digits = 4) => v === null || v === undefined ? "—" : v.toFixed(digits);
const pct = (v: number | null | undefined) => v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`;

/**
 * D3: camera-behaviour windows (activity, schooling/spread, surface proxy).
 * Replaces the per-track LLM narration with measured 5-minute windows and a
 * 7-day hour-of-day baseline. Explicitly EXPERIMENTAL: without a DO sensor the
 * proxies are not calibrated against oxygen events, and surface proximity is
 * not proof of gasping.
 */
export default function BehaviorPanel({ backendConnected }: { backendConnected: boolean }) {
  const [data, setData] = useState<BehaviorStatsData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!backendConfigured || !backendConnected) return;
    setBusy(true);
    try {
      setData(await getBehaviorStats());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [backendConnected]);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => { if (!document.hidden) void load(); }, REFRESH_MS);
    return () => window.clearInterval(id);
  }, [load]);

  const latest = data?.latest;
  const anomaly = data?.anomaly;
  const series = (data?.series ?? []).map((s) => ({
    t: s.t, activity: s.activity !== null && s.activity !== undefined ? s.activity * 1000 : null,
    surface: s.surface !== null && s.surface !== undefined ? s.surface * 100 : null,
  }));

  return (
    <Panel title="Fish Behaviour (camera windows)" subtitle="5-minute windows from confirmed tracks · baseline 7 days, hour-of-day · PROVISIONAL"
      action={<><Badge tone="warn">Experimental</Badge><Badge tone={anomaly ? "bad" : "mute"}>{anomaly ? "Anomaly" : "Normal"}</Badge>
        <button onClick={() => void load()} disabled={busy} aria-label="Refresh behaviour windows"
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-line bg-[var(--surface-1)] text-ink hover:bg-surface disabled:opacity-50">
          <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} /></button></>}>
      {!backendConfigured || !backendConnected ? (
        <p className="text-sm text-mute">Connect the backend to compute behaviour windows. Nothing is inferred in the browser.</p>
      ) : error ? (
        <p role="alert" className="flex items-start gap-1.5 text-sm text-bad"><TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />{error}</p>
      ) : !data ? (
        <p className="text-sm text-mute">Loading behaviour windows…</p>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-2)]/60 p-3">
              <p className="text-xs text-mute">Activity (diagonal/s)</p>
              <p className="mt-1 text-lg font-semibold text-ink">{fmt(latest?.activity_norm)}</p>
              <p className="text-[11px] text-mute">track speed ÷ frame diagonal</p>
            </div>
            <div className="rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-2)]/60 p-3">
              <p className="text-xs text-mute">Schooling spread</p>
              <p className="mt-1 text-lg font-semibold text-ink">{fmt(latest?.spread_norm)}</p>
              <p className="text-[11px] text-mute">pairwise centroid distance ÷ diagonal</p>
            </div>
            <div className="rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-2)]/60 p-3">
              <p className="text-xs text-mute">Surface proxy (top 15%)</p>
              <p className="mt-1 text-lg font-semibold text-ink">{pct(latest?.surface_occ)}</p>
              <p className="text-[11px] text-mute">track time near the surface — not proof of gasping</p>
            </div>
          </div>
          {anomaly && (
            <p role="status" className="flex items-start gap-1.5 rounded-lg border border-warn/40 bg-warn/10 p-2 text-xs text-warn">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
              {anomaly.metric} z={anomaly.z} — different from normal for 15 min (3 windows). Use this as a prompt to check aeration and water; it is not a diagnosis.
            </p>
          )}
          {series.length >= 2 ? (
            <div className="h-40" aria-label="24-hour behaviour windows">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={series} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]}
                    tick={{ fontSize: 10, fill: "var(--text-secondary)" }} tickFormatter={(t: number) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} />
                  <YAxis yAxisId="l" width={34} tick={{ fontSize: 10, fill: "var(--text-secondary)" }} />
                  <YAxis yAxisId="r" orientation="right" width={30} tick={{ fontSize: 10, fill: "var(--text-secondary)" }} />
                  <Tooltip contentStyle={{ background: "var(--surface-2)", border: "1px solid var(--border-subtle)", borderRadius: 8, fontSize: 12, color: "var(--text-primary)" }}
                    labelFormatter={(t) => new Date(Number(t) * 1000).toLocaleString()}
                    formatter={(v, name) => [typeof v === "number" ? v.toFixed(2) : "—", name === "activity" ? "Activity ×1000" : "Surface %"]} />
                  <Line yAxisId="l" type="monotone" dataKey="activity" stroke="var(--accent)" strokeWidth={1.75} dot={false} isAnimationActive={false} connectNulls />
                  <Line yAxisId="r" type="monotone" dataKey="surface" stroke="var(--warn)" strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : <p className="text-xs text-mute">Collecting 24-hour behavior data…</p>}
          <p className="text-[11px] text-mute">
            Baseline: {data.baseline.days}/7 days, {data.baseline.windows} windows ({data.baseline.hours_covered} h) ·
            {data.baseline.ok ? " full 7-day baseline available" : " not enough 7-day baseline yet — owner verification pending"}
          </p>
          <p className="text-[11px] text-mute">{data.disclaimer}</p>
        </div>
      )}
    </Panel>
  );
}
