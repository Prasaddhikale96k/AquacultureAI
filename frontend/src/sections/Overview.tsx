import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Bell,
  Camera,
  Droplets,
  Fish,
  FlaskConical,
  Gauge,
  RefreshCw,
  ShieldCheck,
  Thermometer,
  Wind,
  Waves,
  type LucideIcon,
} from "lucide-react";
import { backendConfigured, getBehaviourSummary, getDashboard, getDoPrediction, getPredictions, markFalseAlarm } from "../services/api";
import type { BehaviourSummary, DashboardData, DoPrediction, Predictions } from "../types";
import { Badge, Skeleton } from "../components/ui";
import { Pill, type PillVariant } from "../components/ui/Pill";
import { useAuth } from "../state/authStore";
import type { Page } from "../components/Shell";

const RULE_LABELS: Record<string, string> = {
  R1: "Sensor feed stopped", R2: "Water temperature out of range", R3: "Rapid temperature change",
  R4: "Turbidity rising fast", R5: "Dawn oxygen risk", R6: "Fish behaviour anomaly",
  R7: "Estimated DO low", R8: "Hypoxia behaviour suspect", R9: "Weak feeding response",
  TEST: "Test message",
};

function ruleName(rule: string) {
  const base = RULE_LABELS[rule] ?? RULE_LABELS[rule.replace(/_RESOLVED$/, "")] ?? "Farm rule";
  return rule.endsWith("_RESOLVED") ? `${base} recovered` : base;
}

function cleanSms(message: string) {
  return message.replace(/^(?:ALERT|RESOLVED) [A-Z0-9_]+:\s*/, "");
}

function riskLabel(level?: string | null) {
  const x = (level ?? "").toLowerCase();
  if (x === "safe" || x === "low" || x === "normal") return "Safe";
  if (x === "watch" || x === "medium") return "Watch";
  if (x === "risk" || x === "high" || x === "warning") return "Risk";
  if (x === "critical" || x === "critical_concern") return "Critical";
  return "No data";
}

function riskVariant(level?: string | null): PillVariant {
  const x = (level ?? "").toLowerCase();
  if (x === "safe" || x === "low" || x === "normal") return "success";
  if (x === "watch" || x === "medium") return "warn";
  if (x === "risk" || x === "high" || x === "warning") return "warn";
  if (x === "critical" || x === "critical_concern") return "critical";
  return "neutral";
}

function riskColor(level?: string | null) {
  const x = (level ?? "").toLowerCase();
  if (x === "safe" || x === "low" || x === "normal") return "var(--success)";
  if (x === "critical" || x === "critical_concern") return "var(--critical)";
  if (x === "watch" || x === "risk" || x === "medium" || x === "high" || x === "warning") return "var(--warn)";
  return "var(--accent)";
}

function behaviourLabel(state?: string | null) {
  if (state === "calm") return "Calm";
  if (state === "restless") return "Restless";
  if (state === "hypoxia_suspect") return "Hypoxia suspected";
  if (state === "warming_up") return "Learning baseline";
  return "No camera data";
}

function ageLabel(value?: number | null, unit: "min" | "h" = "min") {
  if (value == null) return "No data";
  const hours = unit === "h" ? value : value / 60;
  if (hours < 1) return "<1h old";
  if (hours < 2) return `${hours.toFixed(1)}h old`;
  if (hours < 48) return `${Math.round(hours)}h old`;
  return `${Math.round(hours / 24)}d old`;
}

function timeLabel(iso?: string | null) {
  if (!iso) return "No snapshot";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "No snapshot" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function clamp(n: number, min: number, max: number) {
  return Math.max(min, Math.min(max, n));
}

/** Re-render every second so "x s ago" and freshness stay current. */
function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const id = window.setInterval(() => setNow(Date.now()), ms); return () => clearInterval(id); }, [ms]);
  return now;
}

const card = "rounded-2xl border border-line bg-[var(--surface-1)] p-4 shadow-[0_1px_2px_rgb(20_23_28/0.04),0_8px_24px_-16px_rgb(20_23_28/0.12)]";

function pick<T>(r: PromiseSettledResult<T>): T | null {
  return r.status === "fulfilled" ? r.value : null;
}

export default function Overview({ onNavigate = () => {} }: { onNavigate?: (p: Page) => void }) {
  const { user } = useAuth();
  const [d, setD] = useState<DashboardData | null>(null);
  const [doPred, setDoPred] = useState<DoPrediction | null>(null);
  const [behaviour, setBehaviour] = useState<BehaviourSummary | null>(null);
  const [forecasts, setForecasts] = useState<Predictions | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [partial, setPartial] = useState<string | null>(null);

  const load = useCallback(async (manual = false) => {
    if (!backendConfigured) {
      setErr("Backend not configured (VITE_API_BASE_URL). Live values will not load.");
      setLoading(false);
      return;
    }
    if (manual) setBusy(true);
    const [dashboard, prediction, behaviourRes, forecastRes] = await Promise.allSettled([
      getDashboard(), getDoPrediction(), getBehaviourSummary(), getPredictions(),
    ]);
    const dashboardData = pick(dashboard);
    setD(dashboardData);
    setDoPred(pick(prediction));
    setBehaviour(pick(behaviourRes));
    setForecasts(pick(forecastRes));
    if (!dashboardData) {
      setErr(dashboard.status === "rejected" ? (dashboard.reason as Error).message : "Farm snapshot unavailable.");
    } else {
      setErr(null);
    }
    const missing = [prediction, behaviourRes, forecastRes].filter((r) => r.status === "rejected").length;
    setPartial(missing ? "Some live panels are temporarily unavailable; the farm snapshot shown is still real." : null);
    setLoading(false);
    setBusy(false);
  }, []);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => { if (!document.hidden) void load(); }, 5000);
    return () => window.clearInterval(id);
  }, [load]);

  const mark = async (id: string) => {
    try { await markFalseAlarm(id); void load(true); } catch (e) { setPartial((e as Error).message); }
  };

  const k = d?.khatra;
  const latest = d?.sensors.latest;
  const stale = d?.sensors.stats.stale_s;
  const dawn = forecasts?.dawn_risk ?? d?.prediction.dawn_risk;
  const doValue = doPred?.status === "ok" ? doPred.do_mgl : null;
  const doRisk = doPred?.risk_level ?? null;
  const smsConfigured = Boolean(d?.sms.textbee_configured || Object.values(d?.sms.providers_configured ?? {}).some(Boolean));
  const farmAlerts = (d?.alerts ?? []).filter((a) => /^R\d+/.test(a.rule));
  const greeting = useMemo(() => {
    const h = new Date().getHours();
    return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
  }, []);
  const firstName = user?.name?.trim().split(/\s+/)[0] || "Farmer";
  const updated = timeLabel(doPred?.generated_at ?? d?.ts);
  const fresh = stale != null && stale <= 60;
  const freshness = stale == null ? "No sensor feed" : fresh ? "Fresh feed" : `Stale ${ageLabel(stale / 60).replace(" old", "")}`;
  const spanHours = d?.sensors.stats.span_hours ?? null;
  const maturity = spanHours == null ? 0 : clamp((spanHours / 168) * 100, 0, 100);

  return (
    <div className="flex flex-col gap-5">
      <section className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--accent)]">Farm snapshot</p>
          <h2 className="mt-1 font-display text-2xl font-semibold tracking-tight text-[var(--text-primary)] sm:text-[28px]">
            {greeting}, {firstName}.
          </h2>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            {user?.tankId ? `Tank ${user.tankId}` : "Your farm"} · updated {updated} · {freshness}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Pill variant="info">PROVISIONAL</Pill>
          <button
            type="button"
            onClick={() => void load(true)}
            disabled={busy}
            className="inline-flex h-9 items-center gap-2 rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-1)] px-3 text-xs font-semibold text-[var(--text-primary)] transition-colors hover:border-[var(--accent)]/50 hover:bg-[var(--surface-2)] disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} aria-hidden />
            Refresh
          </button>
        </div>
      </section>

      {latest && (
        <section aria-label="Live sensor readings" className="grid gap-3 sm:grid-cols-2">
          <LiveSensorCard
            label="Temperature"
            value={latest.temperature ?? doPred?.inputs.temp_c}
            unit="°C"
            ageMs={latest.t ? Date.now() - latest.t * 1000 : null}
            icon={Thermometer}
            source="DS18B20 · ThingSpeak"
          />
          <LiveSensorCard
            label="Turbidity"
            value={latest.turbidity ?? doPred?.inputs.turbidity_ntu}
            unit="ADC"
            ageMs={latest.t ? Date.now() - latest.t * 1000 : null}
            icon={Droplets}
            source="Turbidity sensor · raw ADC, not NTU"
          />
        </section>
      )}

      {err && (
        <p role="alert" className="flex items-start gap-2 rounded-card border border-[var(--warn)]/35 bg-[var(--warn)]/10 p-3 text-sm text-[var(--warn)]">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {err}
        </p>
      )}
      {partial && !err && (
        <p role="status" className="rounded-card border border-[var(--border-subtle)] bg-[var(--surface-2)]/60 p-2.5 text-[11px] text-[var(--text-secondary)]">
          {partial}
        </p>
      )}

      {loading && !d ? (
        <OverviewSkeleton />
      ) : (
        <>
          <div className="grid gap-4 xl:grid-cols-12">
            <section className="relative overflow-hidden rounded-[20px] border border-[var(--border-subtle)] bg-[var(--surface-1)] xl:col-span-8">
              <div className="pointer-events-none absolute -right-24 -top-28 h-72 w-72 rounded-full bg-[var(--accent)]/10 blur-3xl" aria-hidden />
              <div className="pointer-events-none absolute -bottom-32 left-1/3 h-64 w-64 rounded-full bg-[var(--info)]/10 blur-3xl" aria-hidden />
              <div className="relative p-5 sm:p-6">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="grid h-9 w-9 place-items-center rounded-nested bg-[var(--accent)]/12 text-[var(--accent)]">
                        <Wind className="h-[18px] w-[18px]" aria-hidden />
                      </span>
                      <div>
                        <h2 className="font-display text-[15px] font-semibold text-[var(--text-primary)]">Dissolved oxygen</h2>
                        <p className="text-[11px] text-[var(--text-secondary)]">Estimated from temperature and turbidity</p>
                      </div>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Pill variant={riskVariant(doRisk)}>{doPred?.status === "ok" ? riskLabel(doRisk) : "Awaiting sensors"}</Pill>
                    {doPred?.confidence && <Badge tone="mute">{doPred.confidence} confidence</Badge>}
                  </div>
                </div>

                <div className="mt-6 grid items-center gap-5 sm:grid-cols-[176px_1fr]">
                  <DoRing value={doValue} level={doRisk} />
                  <div className="min-w-0">
                    {doValue != null ? (
                      <>
                        <div className="flex flex-wrap items-end gap-x-2 gap-y-1">
                          <p className="nums font-display text-5xl font-semibold leading-none tracking-tight text-[var(--text-primary)]">{doValue.toFixed(1)}</p>
                          <p className="pb-1 text-sm font-medium text-[var(--text-secondary)]">mg/L</p>
                        </div>
                        <p className="mt-2 text-xs text-[var(--text-secondary)]">
                          Likely range <b className="nums text-[var(--text-primary)]">{doPred?.band_low?.toFixed(1) ?? "—"}–{doPred?.band_high?.toFixed(1) ?? "—"} mg/L</b>
                          {doPred?.percent_saturation != null ? ` · ${Math.round(doPred.percent_saturation)}% saturation` : ""}
                        </p>
                      </>
                    ) : (
                      <>
                        <p className="font-display text-2xl font-semibold text-[var(--text-primary)]">Estimate needs fresh sensors</p>
                        <p className="mt-2 max-w-lg text-sm leading-relaxed text-[var(--text-secondary)]">{doPred?.reason ?? "Temperature or turbidity is missing or stale, so no DO number is shown."}</p>
                      </>
                    )}
                    <div className="mt-4">
                      <BandBar value={doValue} low={doPred?.band_low ?? null} high={doPred?.band_high ?? null} />
                    </div>
                  </div>
                </div>

                <div className="mt-5 grid grid-cols-1 gap-2 sm:grid-cols-3">
                  <InputTile icon={Thermometer} label="Temperature" value={doPred?.inputs.temp_c ?? latest?.temperature} unit="°C" age={ageLabel(doPred?.inputs.temp_age_min)} />
                  <InputTile icon={Waves} label="Turbidity" value={doPred?.inputs.turbidity_ntu ?? latest?.turbidity} unit="ADC" age={ageLabel(doPred?.inputs.turbidity_age_min)} />
                  <InputTile icon={FlaskConical} label="Manual pH" value={doPred?.inputs.ph} unit="pH" age={ageLabel(doPred?.inputs.ph_age_hours, "h")} />
                </div>

                <div className="mt-4 flex flex-col gap-2 rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-2)]/55 p-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[var(--text-secondary)]">
                    <span className="inline-flex items-center gap-1.5"><Fish className="h-3.5 w-3.5 text-[var(--accent)]" aria-hidden />Behaviour: <b className="text-[var(--text-primary)]">{behaviourLabel(behaviour?.state)}</b></span>
                    {behaviour?.hbs != null && <span>Behaviour score <b className="nums text-[var(--text-primary)]">{Math.round(behaviour.hbs)}/100</b></span>}
                    {doPred?.feed_evidence?.last_feed_age_h != null && <span>Last feed <b className="text-[var(--text-primary)]">{doPred.feed_evidence.last_feed_age_h.toFixed(1)}h ago</b></span>}
                  </div>
                  <button type="button" onClick={() => onNavigate("predictions")} className="inline-flex items-center gap-1 text-xs font-semibold text-[var(--link)] hover:underline">
                    See forecast <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </div>
                {doPred?.feed_evidence?.advisory && (
                  <p className="mt-2 flex items-start gap-1.5 text-[11px] text-[var(--warn)]">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />{doPred.feed_evidence.advisory}
                  </p>
                )}
                {doPred?.behaviour_evidence && (
                  <p className="mt-2 flex items-start gap-1.5 text-[11px] text-[var(--critical)]">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                    Camera evidence raised risk one band; numeric DO estimate is unchanged.
                  </p>
                )}
                <div className="mt-4 flex flex-col gap-3 rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-1)] p-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-start gap-2.5">
                    <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-nested ${doValue == null ? "bg-[var(--warn)]/12 text-[var(--warn)]" : "bg-[var(--success)]/12 text-[var(--success)]"}`}>
                      {doValue == null ? <AlertTriangle className="h-4 w-4" aria-hidden /> : <ShieldCheck className="h-4 w-4" aria-hidden />}
                    </span>
                    <div>
                      <p className="text-xs font-semibold text-[var(--text-primary)]">{doValue == null ? "Sensor feed needs attention" : "Estimate is live"}</p>
                      <p className="mt-0.5 max-w-xl text-[11px] leading-relaxed text-[var(--text-secondary)]">
                        {doValue == null
                          ? `${freshness}. The DO estimate stays paused until temperature and turbidity are fresh; risk rules remain active.`
                          : `Based on ${ageLabel(doPred?.inputs.temp_age_min)} and ${ageLabel(doPred?.inputs.turbidity_age_min)}. Confirm with a manual reading at dawn.`}
                      </p>
                    </div>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <button type="button" onClick={() => onNavigate("sensors")} className="inline-flex h-8 items-center rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-2)] px-2.5 text-[11px] font-semibold text-[var(--text-primary)] hover:border-[var(--accent)]/50">Check sensors</button>
                    <button type="button" onClick={() => onNavigate("water")} className="inline-flex h-8 items-center rounded-nested bg-[var(--accent)] px-2.5 text-[11px] font-semibold text-[var(--accent-contrast)] hover:opacity-90">Log water test</button>
                  </div>
                </div>
              </div>
            </section>

            <div className="grid gap-4 xl:col-span-4">
              <section className="rounded-[20px] border border-[var(--border-subtle)] bg-[var(--surface-1)] p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 className="font-display text-[15px] font-semibold text-[var(--text-primary)]">Farm risk</h2>
                    <p className="mt-0.5 text-[11px] text-[var(--text-secondary)]">Khatra score · active farm rules</p>
                  </div>
                  <Pill variant={riskVariant(k?.level)}>{k ? riskLabel(k.level) : "No data"}</Pill>
                </div>
                <div className="mt-5 flex items-center gap-4">
                  <RiskRing score={k?.score ?? null} level={k?.level ?? null} />
                  <div className="min-w-0">
                    <p className="font-display text-2xl font-semibold text-[var(--text-primary)]">
                      {k?.score != null ? <>{k.score}<span className="text-xs font-medium text-[var(--text-secondary)]">/100</span></> : "—"}
                    </p>
                    <p className="mt-1 text-[11px] leading-relaxed text-[var(--text-secondary)]">
                      {k?.active.length ? `${k.active.length} active rule${k.active.length === 1 ? "" : "s"}` : "No rule active right now"}
                    </p>
                  </div>
                </div>
                <ul className="mt-4 space-y-1.5">
                  {k?.active.slice(0, 3).map((r) => (
                    <li key={r.rule} className="flex items-start gap-2 text-[11px] text-[var(--text-secondary)]">
                      <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: riskColor(r.level) }} aria-hidden />
                      <span><b className="font-medium text-[var(--text-primary)]">{ruleName(r.rule)}</b> · {cleanSms(r.message)}</span>
                    </li>
                  ))}
                  {!k?.active.length && <li className="text-[11px] text-[var(--text-secondary)]">The deterministic rules have not flagged the current readings.</li>}
                </ul>
                <button type="button" onClick={() => onNavigate("alerts")} className="mt-4 inline-flex items-center gap-1 text-xs font-semibold text-[var(--link)] hover:underline">
                  Open alerts <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                </button>
              </section>

              <section className="rounded-[20px] border border-[var(--border-subtle)] bg-[var(--surface-1)] p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 className="font-display text-[15px] font-semibold text-[var(--text-primary)]">Tank & system</h2>
                    <p className="mt-0.5 text-[11px] text-[var(--text-secondary)]">{user?.tankId ? `Tank ${user.tankId}` : "Tank profile"}</p>
                  </div>
                  <span className="grid h-9 w-9 place-items-center rounded-nested bg-[var(--surface-2)] text-[var(--accent)]"><Fish className="h-4 w-4" aria-hidden /></span>
                </div>
                <dl className="mt-4 space-y-2 text-xs">
                  <Row label="Species" value={user?.species || "Not set"} />
                  <Row label="System" value={user?.system || "Not set"} />
                  <Row label="Sensors" value={d?.sensors.stats.configured ? freshness : "Not configured"} tone={stale != null && stale > 60 ? "warn" : undefined} />
                  <Row label="SMS gateway" value={smsConfigured ? "Configured" : "Not configured"} tone={smsConfigured ? undefined : "warn"} />
                </dl>
                <div className="mt-4 grid grid-cols-2 gap-2">
                  <Action icon={Droplets} label="Water log" onClick={() => onNavigate("water")} />
                  <Action icon={Bell} label="Alerts" onClick={() => onNavigate("alerts")} />
                  <Action icon={Camera} label="Live camera" onClick={() => onNavigate("monitoring")} />
                  <Action icon={Activity} label="Behaviour" onClick={() => onNavigate("behavior")} />
                </div>
              </section>
            </div>
          </div>

          <section aria-label="Water quality right now">
            <SectionHead title={fresh ? "Water quality right now" : "Water quality snapshot"} subtitle={`${fresh ? "Live ThingSpeak mirror" : "Latest available values"}; each tile carries its own age. Raw ADC is never relabelled as NTU.`} action={<Pill variant="neutral">{freshness}</Pill>} />
            <ul className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Metric icon={Thermometer} label="Temperature" value={doPred?.inputs.temp_c ?? latest?.temperature} unit="°C" note={ageLabel(doPred?.inputs.temp_age_min)} />
              <Metric icon={Waves} label="Turbidity" value={doPred?.inputs.turbidity_ntu ?? latest?.turbidity} unit="ADC" note={`${ageLabel(doPred?.inputs.turbidity_age_min)} · raw ADC, not NTU`} />
              <Metric icon={FlaskConical} label="Manual pH" value={doPred?.inputs.ph} unit="pH" note={doPred?.inputs.ph == null ? "Not logged in the last 24 h" : ageLabel(doPred.inputs.ph_age_hours, "h")} />
              <Metric icon={Wind} label="Estimated DO" value={doValue} unit="mg/L" note={doValue == null ? "Needs fresh sensors" : `${riskLabel(doRisk)} · provisional`} tone={doValue == null ? undefined : doRisk === "critical" ? "bad" : doRisk === "risk" ? "warn" : "ok"} />
            </ul>
          </section>

          <div className="grid gap-4 lg:grid-cols-12">
            <section className="rounded-card border border-[var(--border-subtle)] bg-[var(--surface-1)] lg:col-span-7">
              <div className="flex items-start justify-between gap-3 border-b border-[var(--border-subtle)] p-5">
                <div>
                  <h2 className="font-display text-[15px] font-semibold text-[var(--text-primary)]">Recent alerts</h2>
                  <p className="mt-0.5 text-[11px] text-[var(--text-secondary)]">Only real rule firings; mark a false alarm to correct the record.</p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge tone={riskVariant(k?.level) === "critical" ? "bad" : riskVariant(k?.level) === "warn" ? "warn" : "mute"}>{k ? `Khatra ${riskLabel(k.level)}` : "No risk data"}</Badge>
                  <Badge tone="mute">{farmAlerts.length}</Badge>
                </div>
              </div>
              {!d ? (
                <div className="p-5"><Skeleton className="h-20" /></div>
              ) : farmAlerts.length === 0 ? (
                <div className="flex items-start gap-3 p-5">
                  <span className="grid h-9 w-9 place-items-center rounded-nested bg-[var(--success)]/12 text-[var(--success)]"><ShieldCheck className="h-4 w-4" aria-hidden /></span>
                  <div>
                    <p className="text-sm font-medium text-[var(--text-primary)]">No alerts on record</p>
                    <p className="mt-0.5 text-[11px] text-[var(--text-secondary)]">The rules are quiet. Keep the main pump on 24x7 and watch the dawn window.</p>
                  </div>
                </div>
              ) : (
                <ul className="divide-y divide-[var(--border-subtle)]">
                  {farmAlerts.slice(0, 4).map((a) => (
                    <li key={a.id} className="flex flex-col gap-1.5 px-5 py-3.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={riskVariant(a.level) === "critical" ? "bad" : riskVariant(a.level) === "warn" ? "warn" : "mute"}>{a.level}</Badge>
                        <span className="text-xs font-semibold text-[var(--text-primary)]">{ruleName(a.rule)}</span>
                        <span className="nums text-[11px] text-[var(--text-secondary)]">{new Date(a.t * 1000).toLocaleString([], { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "short" })}</span>
                        <Badge tone={a.delivered ? "ok" : "mute"}>{a.delivered ? "SMS delivered" : "Log only"}</Badge>
                        {a.false_alarm ? <Badge tone="mute">False alarm</Badge> : (
                          <button type="button" onClick={() => void mark(a.id)} className="ml-auto text-[11px] text-[var(--link)] hover:underline">Not an alert?</button>
                        )}
                      </div>
                      <p className="max-w-3xl text-[11px] leading-relaxed text-[var(--text-secondary)]">{cleanSms(a.message)}</p>
                    </li>
                  ))}
                </ul>
              )}
              <div className="flex items-center justify-between gap-2 border-t border-[var(--border-subtle)] p-4">
                <p className="text-[11px] text-[var(--text-secondary)]">Advice only. No pump, feeder or relay is controlled.</p>
                <button type="button" onClick={() => onNavigate("alerts")} className="inline-flex items-center gap-1 text-xs font-semibold text-[var(--link)] hover:underline">
                  All alerts <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                </button>
              </div>
            </section>

            <section className="rounded-card border border-[var(--border-subtle)] bg-[var(--surface-1)] p-5 lg:col-span-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="font-display text-[15px] font-semibold text-[var(--text-primary)]">Dawn oxygen outlook</h2>
                  <p className="mt-0.5 text-[11px] text-[var(--text-secondary)]">7-day sensor maturity · peak risk near 04:30</p>
                </div>
                <Pill variant={riskVariant(dawn?.level)}>{riskLabel(dawn?.level)}</Pill>
              </div>
              <div className="mt-4 flex items-end justify-between gap-3">
                <div>
                  <p className="nums font-display text-3xl font-semibold text-[var(--text-primary)]">{dawn?.score != null ? dawn.score.toFixed(2) : "—"}</p>
                  <p className="text-[11px] text-[var(--text-secondary)]">{dawn?.score != null ? "Dawn risk score / 1.00" : "Cannot compute yet"}</p>
                </div>
                <MiniSpark values={(forecasts?.temperature.points ?? []).map((p) => p.value)} />
              </div>
              <p className="mt-3 text-[11px] leading-relaxed text-[var(--text-secondary)]">
                {dawn?.score != null ? "Proxy from temperature saturation and turbidity; not a DO measurement." : dawn?.reason ?? "Needs 7 days of continuous sensor data before it will forecast."}
              </p>
              <div className="mt-4">
                <div className="flex items-center justify-between text-[10px] font-medium text-[var(--text-secondary)]">
                  <span>7-day sensor maturity</span>
                  <span className="nums">{spanHours != null ? `${spanHours.toFixed(1)} / 168 h` : "—"}</span>
                </div>
                <div className="mt-1.5 h-1.5 rounded-full bg-[var(--surface-3)]"><div className="h-1.5 rounded-full bg-[var(--accent)]" style={{ width: `${maturity}%` }} /></div>
                <p className="mt-1.5 text-[10px] leading-relaxed text-[var(--text-secondary)]">The forecast unlocks after 7 continuous days; it stays hidden until then rather than guessing.</p>
              </div>
              {dawn?.components && (
                <ul className="mt-3 space-y-2 text-[11px]">
                  <Component label="Oxygen saturation drop" value={dawn.components.temperature_saturation_drop} />
                  <Component label="Day/night turbidity swing" value={dawn.components.turbidity_diurnal_swing} />
                  <Component label="Turbidity rise in 24 h" value={dawn.components.turbidity_24h_rise} />
                </ul>
              )}
              <div className="mt-4 grid grid-cols-2 gap-2">
                <MiniStat label="6 h temp" value={forecasts?.temperature.points[forecasts.temperature.points.length - 1]?.value} unit="°C" />
                <MiniStat label="6 h turbidity" value={forecasts?.turbidity.points[forecasts.turbidity.points.length - 1]?.value} unit="ADC" />
              </div>
              <button type="button" onClick={() => onNavigate("predictions")} className="mt-4 inline-flex items-center gap-1 text-xs font-semibold text-[var(--link)] hover:underline">
                Open forecasts <ArrowRight className="h-3.5 w-3.5" aria-hidden />
              </button>
            </section>
          </div>

          <p className="px-1 text-center text-[11px] leading-relaxed text-[var(--text-secondary)]">
            {d?.disclaimer ?? "Experimental research tool. Thresholds are provisional and unvalidated; no fish-health diagnosis or automated control."}
          </p>
        </>
      )}
    </div>
  );
}

function OverviewSkeleton() {
  return (
    <div className="grid gap-4 xl:grid-cols-12" aria-busy="true" aria-label="Loading farm snapshot">
      <div className="rounded-[20px] border border-[var(--border-subtle)] bg-[var(--surface-1)] p-6 xl:col-span-8">
        <Skeleton className="h-7 w-48" />
        <div className="mt-6 flex gap-5">
          <Skeleton className="h-40 w-40 rounded-full" />
          <div className="flex-1 space-y-3">
            <Skeleton className="h-12 w-40" />
            <Skeleton className="h-4 w-56" />
            <Skeleton className="h-2.5 w-full" />
            <div className="grid grid-cols-3 gap-2"><Skeleton className="h-16" /><Skeleton className="h-16" /><Skeleton className="h-16" /></div>
          </div>
        </div>
      </div>
      <div className="grid gap-4 xl:col-span-4">
        <div className="rounded-[20px] border border-[var(--border-subtle)] bg-[var(--surface-1)] p-5"><Skeleton className="h-44" /></div>
        <div className="rounded-[20px] border border-[var(--border-subtle)] bg-[var(--surface-1)] p-5"><Skeleton className="h-44" /></div>
      </div>
    </div>
  );
}

function SectionHead({ title, subtitle, action }: { title: string; subtitle: string; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-2">
      <div>
        <h2 className="font-display text-[15px] font-semibold text-[var(--text-primary)]">{title}</h2>
        <p className="mt-0.5 text-[11px] text-[var(--text-secondary)]">{subtitle}</p>
      </div>
      {action}
    </div>
  );
}

function DoRing({ value, level }: { value: number | null; level?: string | null }) {
  const pct = value == null ? 0 : clamp(value / 8, 0, 1) * 100;
  const color = value == null ? "var(--surface-3)" : riskColor(level);
  return (
    <div className="relative mx-auto grid h-40 w-40 place-items-center rounded-full" style={{ background: `conic-gradient(${color} ${pct * 3.6}deg, var(--surface-3) 0deg)` }} role="img" aria-label={value == null ? "Dissolved oxygen unavailable" : `Dissolved oxygen ${value.toFixed(1)} milligrams per litre`}>
      <div className="absolute inset-[10px] rounded-full bg-[var(--surface-1)] shadow-[inset_0_0_0_1px_var(--border-subtle)]" />
      <div className="relative text-center">
        <Wind className="mx-auto h-4 w-4 text-[var(--accent)]" aria-hidden />
        <p className="nums mt-1 font-display text-3xl font-semibold text-[var(--text-primary)]">{value == null ? "—" : value.toFixed(1)}</p>
        <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-[var(--text-secondary)]">mg/L</p>
      </div>
    </div>
  );
}

function RiskRing({ score, level }: { score: number | null; level?: string | null }) {
  const pct = score == null ? 0 : clamp(score, 0, 100);
  const color = score == null ? "var(--surface-3)" : level === "LOW" ? "var(--success)" : level === "HIGH" ? "var(--critical)" : "var(--warn)";
  return (
    <div className="relative grid h-24 w-24 shrink-0 place-items-center rounded-full" style={{ background: `conic-gradient(${color} ${pct * 3.6}deg, var(--surface-3) 0deg)` }} role="img" aria-label={score == null ? "Farm risk unavailable" : `Farm risk ${score} out of 100`}>
      <div className="absolute inset-2 rounded-full bg-[var(--surface-1)]" />
      <div className="relative text-center">
        <Gauge className="mx-auto h-3.5 w-3.5 text-[var(--text-secondary)]" aria-hidden />
        <p className="nums mt-0.5 font-display text-lg font-semibold text-[var(--text-primary)]">{score ?? "—"}</p>
      </div>
    </div>
  );
}

function BandBar({ value, low, high }: { value: number | null; low: number | null; high: number | null }) {
  const x = (v: number) => `${clamp(v / 8, 0, 1) * 100}%`;
  return (
    <div>
      <div className="relative h-2.5 rounded-full bg-[var(--surface-3)]" aria-hidden>
        <span className="absolute inset-y-0 left-0 w-[25%] rounded-l-full bg-[var(--critical)]/20" />
        <span className="absolute inset-y-0 left-[25%] w-[18.75%] bg-[var(--warn)]/20" />
        <span className="absolute inset-y-0 left-[43.75%] right-0 rounded-r-full bg-[var(--success)]/20" />
        {low != null && high != null && <span className="absolute inset-y-0 rounded-full border-x border-[var(--accent)]/40 bg-[var(--accent)]/20" style={{ left: x(low), width: `${clamp((high - low) / 8, 0, 1) * 100}%` }} />}
        {value != null && <span className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[var(--surface-1)] bg-[var(--text-primary)] shadow" style={{ left: x(value) }} />}
      </div>
      <div className="mt-1.5 flex justify-between text-[9px] font-medium uppercase tracking-[0.08em] text-[var(--text-secondary)]">
        <span>0</span><span className="text-[var(--critical)]">2 critical</span><span className="text-[var(--warn)]">3.5 watch</span><span className="text-[var(--success)]">5+ safe</span><span>8</span>
      </div>
    </div>
  );
}

function InputTile({ icon: Icon, label, value, unit, age }: { icon: LucideIcon; label: string; value: number | null | undefined; unit: string; age: string }) {
  return (
    <div className="rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-2)]/55 p-3">
      <p className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-[0.1em] text-[var(--text-secondary)]"><Icon className="h-3.5 w-3.5 text-[var(--accent)]" aria-hidden />{label}</p>
      <p className="nums mt-1 text-lg font-semibold text-[var(--text-primary)]">{value != null ? (unit === "ADC" ? Math.round(value) : value.toFixed(unit === "pH" ? 2 : 1)) : "—"}<span className="ml-1 text-[10px] font-medium text-[var(--text-secondary)]">{unit}</span></p>
      <p className="text-[10px] text-[var(--text-secondary)]">{age}</p>
    </div>
  );
}

function Metric({ icon: Icon, label, value, unit, note, tone }: { icon: LucideIcon; label: string; value: number | null | undefined; unit: string; note: string; tone?: "ok" | "warn" | "bad" }) {
  const color = tone === "bad" ? "text-[var(--critical)]" : tone === "warn" ? "text-[var(--warn)]" : tone === "ok" ? "text-[var(--success)]" : "text-[var(--text-primary)]";
  return (
    <li className="rounded-card border border-[var(--border-subtle)] bg-[var(--surface-1)] p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-[11px] font-medium text-[var(--text-secondary)]"><span className="grid h-7 w-7 place-items-center rounded-nested bg-[var(--surface-2)] text-[var(--accent)]"><Icon className="h-3.5 w-3.5" aria-hidden /></span>{label}</span>
      </div>
      <p className={`nums mt-3 font-display text-2xl font-semibold ${color}`}>{value != null ? (unit === "ADC" ? Math.round(value) : value.toFixed(unit === "pH" ? 2 : 1)) : "—"}<span className="ml-1 text-[11px] font-medium text-[var(--text-secondary)]">{unit}</span></p>
      <p className="mt-1 text-[10px] leading-relaxed text-[var(--text-secondary)]">{note}</p>
    </li>
  );
}

function Row({ label, value, tone }: { label: string; value: string; tone?: "warn" }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-[var(--text-secondary)]">{label}</dt>
      <dd className={`truncate font-medium ${tone === "warn" ? "text-[var(--warn)]" : "text-[var(--text-primary)]"}`}>{value}</dd>
    </div>
  );
}

function Action({ icon: Icon, label, onClick }: { icon: LucideIcon; label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="inline-flex min-h-9 items-center gap-2 rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-2)]/60 px-2.5 text-left text-[11px] font-medium text-[var(--text-primary)] transition-colors hover:border-[var(--accent)]/45 hover:bg-[var(--surface-2)]">
      <Icon className="h-3.5 w-3.5 text-[var(--accent)]" aria-hidden />{label}
    </button>
  );
}

function Component({ label, value }: { label: string; value?: number }) {
  const pct = value == null ? 0 : clamp(value * 100, 0, 100);
  return (
    <li>
      <div className="flex items-center justify-between gap-2"><span className="text-[var(--text-secondary)]">{label}</span><span className="nums font-medium text-[var(--text-primary)]">{value != null ? value.toFixed(2) : "—"}</span></div>
      <div className="mt-1 h-1.5 rounded-full bg-[var(--surface-3)]"><div className="h-1.5 rounded-full bg-[var(--accent)]" style={{ width: `${pct}%` }} /></div>
    </li>
  );
}

function MiniStat({ label, value, unit }: { label: string; value?: number; unit: string }) {
  return (
    <div className="rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-2)]/55 p-2.5">
      <p className="text-[10px] text-[var(--text-secondary)]">{label}</p>
      <p className="nums mt-0.5 text-sm font-semibold text-[var(--text-primary)]">{value != null ? (unit === "ADC" ? Math.round(value) : value.toFixed(1)) : "—"} <span className="text-[10px] font-normal text-[var(--text-secondary)]">{unit}</span></p>
    </div>
  );
}


function LiveSensorCard({ label, value, unit, ageMs, icon: Icon, source }: { label: string; value: number | null | undefined; unit: string; ageMs: number | null; icon: LucideIcon; source: string }) {
  useNow();
  const fresh = ageMs != null ? Math.max(0, Math.min(100, Math.round(100 * (1 - ageMs / 1200000)))) : null;
  const status = ageMs == null ? "not_configured" : ageMs < 60000 ? "live" : ageMs < 3600000 ? "stale" : "no_data";
  const [labelS, dot] = status === "live" ? ["Live", "bg-brand"] : status === "stale" ? ["Stale", "bg-warn"] : status === "no_data" ? ["No Data Available", "bg-slate-300"] : ["Not Configured", "bg-slate-300"];
  const ago = ageMs == null ? "—" : ageMs < 60_000 ? `${Math.round(ageMs / 1000)} s ago` : ageMs < 3_600_000 ? `${Math.round(ageMs / 60_000)} min ago` : `${(ageMs / 3_600_000).toFixed(1)} h ago`;
  return (
    <li className={card} data-testid={`card-${label.toLowerCase()}`}>
      <div className="flex items-center gap-2 text-sm font-medium text-ink">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-brand/10"><Icon className="h-4 w-4 text-brand" /></span>{label}
      </div>
      <div className="mt-4 flex items-start justify-between gap-2">
        <p className="text-3xl font-bold text-ink">
          {value != null ? <>{value}<span className="ml-1 text-xs font-medium text-mute">{unit}</span></> : <span className="text-lg font-semibold text-mute">No valid reading</span>}
        </p>
        {fresh != null ? (
          <span className={`flex items-center gap-1 text-xs font-medium ${fresh > 60 ? "text-[var(--success)]" : fresh > 30 ? "text-[var(--warn)]" : "text-[var(--critical)]"}`}>
            Fresh {fresh}%
          </span>
        ) : null}
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
        <div><dt className="font-semibold uppercase tracking-wide text-mute">Last reading</dt><dd className="mt-0.5 text-ink">{ago}</dd></div>
        <div><dt className="font-semibold uppercase tracking-wide text-mute">Source</dt><dd className="mt-0.5 text-ink">{source}</dd></div>
      </dl>
      <div className="mt-2 flex items-center justify-between text-[11px]">
        <span className="flex items-center gap-1.5 font-medium text-ink"><span className={`h-1.5 w-1.5 rounded-full ${dot}`} />{labelS}</span>
        <span className="text-mute">{unit === "ADC" ? "raw, uncalibrated — not NTU" : source}</span>
      </div>
    </li>
  );
}

function MiniSpark({ values }: { values: number[] }) {
  if (values.length < 2) return <span className="grid h-10 w-24 place-items-center rounded-nested bg-[var(--surface-2)] text-[10px] text-[var(--text-secondary)]">No trend</span>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = values.map((v, i) => `${(i / (values.length - 1)) * 100},${28 - ((v - min) / span) * 24}`).join(" ");
  return (
    <svg viewBox="0 0 100 30" className="h-10 w-24" role="img" aria-label="Short-term temperature trend">
      <polyline points={points} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
