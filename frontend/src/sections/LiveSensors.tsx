import { useEffect, useState } from "react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowDown, ArrowUp, Droplet, FlaskConical, Minus, Sparkles, Thermometer, Wind, type LucideIcon } from "lucide-react";
import { SENSOR_KEYS, statusOf, type Mapping, type SensorKey, type SensorStatus } from "../services/thingspeak";
import type { Sensors } from "../hooks/useSensors";
import { LABELS, UNITS, describeTemperature, freshness } from "../config/alerts";
import { Badge } from "../components/ui";
import { thingSpeakStatus } from "./StatusPanels";

const ICON: Record<SensorKey, LucideIcon> = { temperature: Thermometer, turbidity: Droplet, ph: FlaskConical, do: Wind };
const SOURCE: Record<SensorKey, string> = { temperature: "DS18B20", turbidity: "Turbidity sensor", ph: "pH sensor", do: "DO sensor" };
const STATUS: Record<SensorStatus, [string, string]> = {
  live: ["Live", "bg-brand"], stale: ["Stale", "bg-warn"], no_data: ["No Data Available", "bg-slate-300"], not_configured: ["Not Configured", "bg-slate-300"],
};
const card = "rounded-2xl border border-line bg-[var(--surface-1)] p-4 shadow-[0_1px_2px_rgb(20_23_28/0.04),0_8px_24px_-16px_rgb(20_23_28/0.12)]";
const hms = (t: number) => new Date(t).toLocaleTimeString([], { hour12: false });

/** Re-render every second so "x s ago" and freshness stay current. */
function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const id = window.setInterval(() => setNow(Date.now()), ms); return () => clearInterval(id); }, [ms]);
  return now;
}
const ago = (ms: number) => (ms < 0 ? "just now" : ms < 60_000 ? `${Math.round(ms / 1000)} s ago` : ms < 3_600_000 ? `${Math.round(ms / 60_000)} min ago` : `${(ms / 3_600_000).toFixed(1)} h ago`);
const sourceText = (k: SensorKey, m?: Mapping[SensorKey]) =>
  !m || m.field === null ? "No field mapped" : `${SOURCE[k]} · Field ${m.field}${m.source === "label" ? " (matched by label, verify)" : ""}`;

export function InsightCard({ s }: { s: Sensors }) {
  const ins = s.readings && s.mapping?.temperature.field ? describeTemperature(s.readings.temperature) : null;
  return (
    <section aria-label="System insight" className="relative flex min-h-[170px] flex-col justify-between overflow-hidden rounded-2xl bg-gradient-to-br from-[#86bff0] to-[#4a9be3] p-5 text-white shadow-[0_12px_30px_-18px_rgb(74_155_227/0.9)]">
      <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-widest text-white/80"><Sparkles className="h-3.5 w-3.5" />System insight</p>
      <p className="my-3 max-w-2xl text-xl font-semibold leading-snug sm:text-2xl">
        {s.problem ? "ThingSpeak is not configured, so there is no sensor insight." : ins ? ins.text : s.error && !s.readings ? "Sensor data could not be fetched." : s.readings ? "Not enough valid temperature readings for an insight yet." : "Loading sensor data…"}
      </p>
      <p className="text-[11px] text-white/85">{ins ? ins.detail : "Insights are derived only from fetched ThingSpeak readings, never invented."}</p>
    </section>
  );
}

export function PipelineCard({ s }: { s: Sensors }) {
  const now = useNow();
  const ts = thingSpeakStatus(s);
  const latest = s.readings ? Math.max(0, ...SENSOR_KEYS.map((k) => s.readings![k].at(-1)?.t ?? 0)) : 0;
  const mapped = s.mapping ? SENSOR_KEYS.filter((k) => s.mapping![k].field !== null) : [];
  const rows: [string, string][] = [
    ["Last successful fetch", s.fetchedAt ? hms(s.fetchedAt) : "None yet"],
    ["Latest measurement", latest ? `${hms(latest)} · ${ago(now - latest)}` : "None yet"],
    ["Configured fields", s.mapping ? `${mapped.length} of 4 · ${mapped.map((k) => (k === "turbidity" ? "Raw Turbidity" : LABELS[k])).join(", ") || "none"}` : "—"],
  ];
  return (
    <section aria-label="Data pipeline" className={card}>
      <h2 className="text-[15px] font-semibold text-ink">Data Pipeline</h2>
      <p className="mt-0.5 text-[11px] text-mute">ESP32 {"→"} USB serial {"→"} Python uploader {"→"} ThingSpeak {"→"} this dashboard (read-only)</p>
      <dl className="mt-3 space-y-2.5 text-xs">
        <div className="flex items-center justify-between gap-3 border-b border-line pb-2"><dt className="text-mute">ThingSpeak read API</dt><dd><Badge tone={ts.tone === "ok" ? "info" : ts.tone === "bad" ? "bad" : ts.tone === "warn" ? "warn" : "mute"}>{ts.value}</Badge></dd></div>
        {rows.map(([k, v]) => <div key={k} className="flex items-start justify-between gap-3 border-b border-line pb-2 last:border-0"><dt className="text-mute">{k}</dt><dd className="text-right font-medium text-ink">{v}</dd></div>)}
      </dl>
    </section>
  );
}

function Gauge({ pct }: { pct: number | null }) {
  const L = Math.PI * 24;
  return (
    <div className="relative w-[64px] text-center" aria-label={pct === null ? "Freshness unavailable" : `Freshness ${pct}%`} title="Freshness: share of the stale limit still remaining. It is not a measure of sensor quality.">
      <svg viewBox="0 0 56 32" className="h-8 w-full">
        <path d="M4 28 A24 24 0 0 1 52 28" fill="none" stroke="#e9edf1" strokeWidth="5" strokeLinecap="round" />
        {pct !== null && <path d="M4 28 A24 24 0 0 1 52 28" fill="none" stroke="#4a9be3" strokeWidth="5" strokeLinecap="round" strokeDasharray={`${(pct / 100) * L} ${L}`} />}
      </svg>
      <p className="-mt-1 text-[8px] font-semibold uppercase tracking-wider text-mute">Freshness</p>
      <p className="text-xs font-semibold text-ink">{pct === null ? "—" : `${pct}%`}</p>
    </div>
  );
}

export function MetricCards({ s }: { s: Sensors }) {
  const now = useNow();
  return (
    <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="Latest readings">
      {SENSOR_KEYS.map((k) => {
        const Icon = ICON[k], pts = s.readings?.[k] ?? [], last = pts.at(-1), prev = pts.at(-2);
        const st: SensorStatus = s.readings ? statusOf(pts, s.mapping?.[k].field ?? null, !s.error) : s.problem ? "not_configured" : "no_data";
        const [label, dot] = STATUS[st];
        const bars = pts.slice(-12), lo = Math.min(...bars.map((p) => p.v)), hi = Math.max(...bars.map((p) => p.v));
        const Trend = !prev || !last || last.v === prev.v ? Minus : last.v > prev.v ? ArrowUp : ArrowDown;
        return (
          <li key={k} className={card} data-testid={`card-${k}`}>
            <div className="flex items-center gap-2 text-sm font-medium text-ink">
              <span className="grid h-7 w-7 place-items-center rounded-lg bg-brand/10"><Icon className="h-4 w-4 text-brand" /></span>{LABELS[k]}
            </div>
            <div className="mt-4 flex items-start justify-between gap-2">
              <p className="text-3xl font-bold text-ink">
                {last ? <>{last.v}<span className="ml-1 text-xs font-medium text-mute">{UNITS[k]}</span><Trend className="ml-1 inline h-3.5 w-3.5 text-mute" aria-hidden /></>
                  : <span className="text-lg font-semibold text-mute">{st === "not_configured" ? "Not Configured" : s.readings || s.error ? "No valid reading" : "Loading…"}</span>}
              </p>
              <Gauge pct={last ? freshness(last.t, s.staleMs, now) : null} />
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
              <div><dt className="font-semibold uppercase tracking-wide text-mute">Last reading</dt><dd className="mt-0.5 text-ink">{last ? ago(now - last.t) : "—"}</dd></div>
              <div><dt className="font-semibold uppercase tracking-wide text-mute">Source</dt><dd className="mt-0.5 text-ink">{s.mapping ? sourceText(k, s.mapping[k]) : "—"}</dd></div>
            </dl>
            <div className="mt-3 flex h-9 items-end gap-1" aria-hidden>
              {bars.length ? bars.map((p, i) => <span key={i} className={`flex-1 rounded-sm ${i === bars.length - 1 ? "bg-brand" : "bg-slate-200"}`} style={{ height: `${hi === lo ? 40 : 20 + (80 * (p.v - lo)) / (hi - lo)}%` }} />)
                : Array.from({ length: 12 }, (_, i) => <span key={i} className="h-1 flex-1 rounded-sm bg-slate-100" />)}
            </div>
            <p className="mt-1 text-[10px] text-mute">{bars.length ? `${bars.length} readings · latest bar highlighted` : "No history · this field is not mapped."}</p>
            <div className="mt-2 flex items-center justify-between text-[11px]">
              <span className="flex items-center gap-1.5 font-medium text-ink"><span className={`h-1.5 w-1.5 rounded-full ${dot}`} />{s.readings || s.error ? label : "Loading…"}</span>
              <span className="text-mute">{k === "turbidity" ? "raw, uncalibrated — not NTU" : s.mapping?.[k].field ? `ThingSpeak Field ${s.mapping[k].field}` : "not configured"}</span>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function HistoryCards({ s }: { s: Sensors }) {
  return (
    <>
      {SENSOR_KEYS.map((k) => {
        const pts = s.readings?.[k] ?? [];
        if (!s.readings || s.mapping?.[k].field === null || pts.length === 0) return null;
        const vs = pts.map((p) => p.v), min = Math.min(...vs), max = Math.max(...vs), avg = vs.reduce((a, b) => a + b, 0) / vs.length;
        const u = UNITS[k], f = (n: number) => (k === "turbidity" ? String(Math.round(n)) : n.toFixed(1));
        return (
          <figure key={k} className={card} aria-label={`${LABELS[k]} history`}>
            <figcaption className="flex items-start justify-between gap-2">
              <div><h3 className="text-sm font-semibold text-ink">{LABELS[k].replace(" (ADC)", "")} History</h3>
                <p className="text-[11px] text-mute">ThingSpeak Field {s.mapping![k].field} {"·"} {u} {"·"} last {pts.length} valid readings{k === "turbidity" ? " · raw, uncalibrated — not NTU" : ""}</p></div>
              <p className="text-2xl font-bold text-ink">{pts.at(-1)!.v}<span className="ml-1 text-[10px] font-medium text-mute">{u}</span></p>
            </figcaption>
            <dl className="mt-2 grid grid-cols-4 gap-2 text-[11px]">
              {([["Min", `${f(min)} ${u}`], ["Max", `${f(max)} ${u}`], ["Avg", `${f(avg)} ${u}`], ["Points", `${pts.length} valid`]] as const).map(([l, v]) => (
                <div key={l}><dt className="font-semibold uppercase tracking-wide text-mute">{l}</dt><dd className="text-ink">{v}</dd></div>
              ))}
            </dl>
            {pts.length < 2 ? <p className="py-8 text-center text-xs text-mute">Not enough readings to draw a trend.</p> : (
              <div className="mt-2 h-40">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={pts} margin={{ top: 4, bottom: 0, left: 0, right: 8 }}>
                    <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} tick={{ fontSize: 10, fill: "#717883" }} tickFormatter={(t: number) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} />
                    <YAxis width={42} domain={["auto", "auto"]} tick={{ fontSize: 10, fill: "#717883" }} />
                    <Tooltip contentStyle={{ background: "#14171c", border: "none", borderRadius: 8, fontSize: 12, color: "#fff" }} labelFormatter={(t) => new Date(Number(t)).toLocaleString()} formatter={(v) => [`${v} ${u}`, LABELS[k]]} />
                    <Area type="monotone" dataKey="v" stroke="#3b8fd9" fill="#4a9be3" fillOpacity={0.14} strokeWidth={1.75} isAnimationActive={false} connectNulls={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </figure>
        );
      })}
    </>
  );
}
