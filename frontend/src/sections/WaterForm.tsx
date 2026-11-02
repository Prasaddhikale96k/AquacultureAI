import { useEffect, useState, type ReactNode } from "react";
import { Loader2, Save, X } from "lucide-react";
import type { InputSource, MeasurementKey, WaterConfig, WaterPayload, WaterRecord } from "../types";
import { FieldError } from "../services/api";

const MEASUREMENTS: { key: MeasurementKey; label: string }[] = [
  { key: "temperature", label: "Temperature" }, { key: "pH", label: "pH" }, { key: "dissolvedOxygen", label: "Dissolved oxygen" },
  { key: "turbidity", label: "Turbidity" }, { key: "ammonia", label: "Total ammonia" },
  { key: "nitrite", label: "Nitrite" }, { key: "nitrate", label: "Nitrate (optional)" }, { key: "salinity", label: "Salinity (optional)" },
];
const UNIT_LABEL: Record<string, string> = { C: "°C", F: "°F", pH: "pH" };
const pretty = (s: string) => s.replace(/_/g, " ");
const toLocalInput = (iso?: string) => {
  const d = iso ? new Date(iso) : new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};

interface Cell { value: string; unit: string; method: string }
const input = "w-full rounded-lg border border-line bg-abyss/60 px-2 py-1.5 text-xs text-white placeholder:text-mute/60 focus:border-cyan";

const Field = ({ label, error, children }: { label: string; error?: string; children: ReactNode }) => (
  <label className="block text-[11px] text-mute">{label}{children}{error && <span role="alert" className="mt-0.5 block text-bad">{error}</span>}</label>
);

export default function WaterForm({ config, tanks, editing, defaultTank, disabledReason, onSubmit, onCancelEdit }: {
  config: WaterConfig | null; tanks: string[]; editing: WaterRecord | null; defaultTank: string; disabledReason?: string;
  onSubmit: (p: WaterPayload) => Promise<void>; onCancelEdit: () => void;
}) {
  const blank = (cfg: WaterConfig | null): Record<MeasurementKey, Cell> =>
    Object.fromEntries(MEASUREMENTS.map(({ key }) => [key, { value: "", unit: cfg?.units[key]?.[0] ?? "", method: "" }])) as Record<MeasurementKey, Cell>;
  const [tankId, setTank] = useState(defaultTank);
  const [ctx, setCtx] = useState({ species: "tilapia", lifeStage: "", system: "ras", source: "manual" as InputSource, timestamp: toLocalInput() });
  const [cells, setCells] = useState(blank(config));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (config && !editing) setCells((c) => (c.temperature.unit ? c : blank(config))); }, [config]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!editing) setTank(defaultTank); }, [defaultTank, editing]);
  useEffect(() => {
    if (!editing) return;
    setTank(editing.tankId);
    setCtx({ species: editing.species, lifeStage: editing.lifeStage ?? "", system: editing.system, source: editing.source, timestamp: toLocalInput(editing.timestamp) });
    const next = blank(config);
    for (const [k, m] of Object.entries(editing.measurements)) next[k as MeasurementKey] = { value: String(m.value), unit: m.unit, method: m.method ?? "" };
    setCells(next); setErrors({});
  }, [editing]); // eslint-disable-line react-hooks/exhaustive-deps

  const setCell = (k: MeasurementKey, patch: Partial<Cell>) => setCells((c) => ({ ...c, [k]: { ...c[k], ...patch } }));

  function build(): { payload?: WaterPayload; errs: Record<string, string> } {
    const errs: Record<string, string> = {};
    if (!config) return { errs: { form: "Configuration not loaded." } };
    if (!/^[\w .-]{1,64}$/.test(tankId.trim())) errs.tankId = "Required (letters, digits, space . _ -).";
    if (!ctx.timestamp || Number.isNaN(new Date(ctx.timestamp).getTime())) errs.timestamp = "Required.";
    else if (new Date(ctx.timestamp).getTime() > Date.now() + 5 * 60000) errs.timestamp = "Cannot be in the future.";
    const measurements: WaterPayload["measurements"] = {};
    for (const { key } of MEASUREMENTS) {
      const c = cells[key];
      if (c.value.trim() === "") continue;                       // left empty = not measured (never sent as 0)
      const v = Number(c.value);
      if (!Number.isFinite(v)) { errs[key] = "Enter a number."; continue; }
      if (key === "ammonia" && !c.method) { errs[key] = "Choose the measurement method."; continue; }
      measurements[key] = { value: v, unit: c.unit, ...(key === "ammonia" ? { method: c.method } : {}) };
    }
    if (Object.keys(measurements).length === 0 && !Object.keys(errs).some((k) => k in cells)) errs.measurements = "Enter at least one measurement.";
    if (Object.keys(errs).length) return { errs };
    return { errs, payload: { tankId: tankId.trim(), species: ctx.species, lifeStage: ctx.lifeStage || null, system: ctx.system, source: ctx.source,
      timestamp: new Date(ctx.timestamp).toISOString(), supersedes: editing?.id ?? null, measurements } };
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const { payload, errs } = build();
    setErrors(errs);
    if (!payload) return;
    setBusy(true);
    try { await onSubmit(payload); if (!editing) setCells(blank(config)); }
    catch (err) { setErrors(err instanceof FieldError ? { ...err.fields, form: err.message } : { form: (err as Error).message }); }
    finally { setBusy(false); }
  }

  const opts = config?.options;
  return (
    <form onSubmit={submit} className="space-y-3" aria-label="Water-quality measurements" noValidate>
      {editing && (
        <p className="flex items-center justify-between rounded-lg border border-warn/30 bg-warn/10 px-2 py-1.5 text-[11px] text-warn">
          Editing a saved reading: saving adds a corrected entry; the original stays in history.
          <button type="button" onClick={onCancelEdit} className="inline-flex items-center gap-1 underline"><X className="h-3 w-3" />Cancel edit</button>
        </p>
      )}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Field label="Tank / pond ID *" error={errors.tankId}>
          <input className={input} list="tank-ids" value={tankId} onChange={(e) => setTank(e.target.value)} placeholder="e.g. Tank 1" disabled={!!editing} />
          <datalist id="tank-ids">{tanks.map((t) => <option key={t} value={t} />)}</datalist>
        </Field>
        <Field label="Species *" error={errors.species}>
          <select className={input} value={ctx.species} onChange={(e) => setCtx({ ...ctx, species: e.target.value })}>{opts?.species.map((s) => <option key={s} value={s}>{pretty(s)}</option>)}</select>
        </Field>
        <Field label="Life stage" error={errors.lifeStage}>
          <select className={input} value={ctx.lifeStage} onChange={(e) => setCtx({ ...ctx, lifeStage: e.target.value })}><option value="">Not stated</option>{opts?.lifeStage.map((s) => <option key={s} value={s}>{pretty(s)}</option>)}</select>
        </Field>
        <Field label="System *" error={errors.system}>
          <select className={input} value={ctx.system} onChange={(e) => setCtx({ ...ctx, system: e.target.value })}>{opts?.system.map((s) => <option key={s} value={s}>{pretty(s)}</option>)}</select>
        </Field>
        <Field label="Measured at *" error={errors.timestamp}>
          <input className={input} type="datetime-local" value={ctx.timestamp} onChange={(e) => setCtx({ ...ctx, timestamp: e.target.value })} />
        </Field>
        <Field label="Source *" error={errors.source}>
          <select className={input} value={ctx.source} onChange={(e) => setCtx({ ...ctx, source: e.target.value as InputSource })}>{opts?.source.map((s) => <option key={s} value={s}>{pretty(s)}</option>)}</select>
        </Field>
      </div>

      <fieldset className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <legend className="mb-1 text-[11px] text-mute">Only pH is entered manually by the farmer; other parameters are not recorded here.</legend>
        {MEASUREMENTS.filter(({ key }) => key === "pH").map(({ key, label }) => (
          <div key={key} className="rounded-lg border border-line/60 bg-surface/30 p-2">
            <Field label={label} error={errors[key]}>
              <div className="mt-0.5 flex gap-1.5">
                <input className={input} inputMode="decimal" value={cells[key].value} onChange={(e) => setCell(key, { value: e.target.value })} aria-label={`${label} value`} />
                {(config?.units[key]?.length ?? 0) > 1 ? (
                  <select className={`${input} w-24`} value={cells[key].unit} onChange={(e) => setCell(key, { unit: e.target.value })} aria-label={`${label} unit`}>
                    {config?.units[key].map((u) => <option key={u} value={u}>{UNIT_LABEL[u] ?? u}</option>)}
                  </select>
                ) : <span className="grid w-24 place-items-center text-[11px] text-mute">{UNIT_LABEL[cells[key].unit] ?? cells[key].unit}</span>}
              </div>
            </Field>
            {key === "ammonia" && (
              <Field label="Method *">
                <select className={`${input} mt-0.5`} value={cells.ammonia.method} onChange={(e) => setCell("ammonia", { method: e.target.value })}>
                  <option value="">Select…</option>{opts?.ammoniaMethod.map((m) => <option key={m} value={m}>{pretty(m)}</option>)}
                </select>
              </Field>
            )}
          </div>
        ))}
      </fieldset>
      {errors.measurements && <p role="alert" className="text-[11px] text-bad">{errors.measurements}</p>}
      {errors.form && <p role="alert" className="rounded-lg border border-bad/30 bg-bad/10 p-2 text-xs text-bad">{errors.form}</p>}
      {disabledReason && <p className="text-[11px] text-warn">{disabledReason}</p>}
      <button type="submit" disabled={busy || !!disabledReason || !config}
        className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-brand to-cyan px-4 py-2 text-sm font-semibold text-abyss disabled:cursor-not-allowed disabled:opacity-40">
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}{editing ? "Save correction & assess" : "Save & assess"}
      </button>
    </form>
  );
}
