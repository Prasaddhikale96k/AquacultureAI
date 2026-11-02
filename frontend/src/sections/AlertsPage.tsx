import { useCallback, useEffect, useState } from "react";
import { Bell, Phone, RefreshCw } from "lucide-react";
import { backendConfigured, getDashboard, getAlertSettings, putAlertSettings, markFalseAlarm, removePhone, sendTestSms } from "../services/api";
import type { AuthUser, DashboardData, TestSmsResult } from "../types";
import { Badge } from "../components/ui";
import SmsSetup from "../components/SmsSetup";

const RULE_EN: Record<string, { label: string; hint: string }> = {
  R1: { label: "Sensor feed stale", hint: "No fresh sensor reading — immediate alert" },
  R2: { label: "Temperature out of range", hint: "Outside 22–34 °C for 10 min" },
  R3: { label: "Rapid temperature change", hint: "More than 2 °C in 60 min" },
  R4: { label: "Turbidity rising", hint: "More than +40% vs 6 h median in 60 min" },
  R5: { label: "Dawn oxygen risk", hint: "Daily advisory at 04:30 local" },
  R6: { label: "Fish behavior anomaly", hint: "Sustained 15 min vs 7-day baseline" },
  TEST: { label: "Test message", hint: "Manual test from this page" },
};
const TONE = (v?: string | null): "ok" | "warn" | "bad" | "mute" => {
  const x = (v ?? "").toUpperCase();
  return x === "HIGH" || x === "CRITICAL" ? "bad" : x === "MEDIUM" || x === "WARNING" ? "warn" : x === "LOW" || x === "NORMAL" ? "ok" : "mute";
};

export default function AlertsPage({ user }: { user: AuthUser }) {
  const [d, setD] = useState<DashboardData | null>(null);
  const [sms, setSms] = useState<TestSmsResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [smsBusy, setSmsBusy] = useState(false);
  const [removeBusy, setRemoveBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [settings, setSettings] = useState<Record<string, number> | null>(null);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [settingsErr, setSettingsErr] = useState<string | null>(null);
  const [settingsSaved, setSettingsSaved] = useState(false);

  const load = useCallback(async () => {
    if (!backendConfigured) { setErr("Backend not configured (VITE_API_BASE_URL)."); return; }
    setBusy(true);
    try { setD(await getDashboard()); setErr(null); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }, []);

  const loadSettings = useCallback(async () => {
    if (!backendConfigured) return;
    try {
      const s = await getAlertSettings();
      setSettings(s.cooldown_min);
      setSettingsErr(null);
    } catch (e) { setSettingsErr((e as Error).message); }
  }, []);

  const saveSettings = async () => {
    if (!settings) return;
    setSettingsBusy(true); setSettingsErr(null); setSettingsSaved(false);
    try {
      const res = await putAlertSettings(settings);
      setSettings(res.cooldown_min);
      setSettingsSaved(true);
      setTimeout(() => setSettingsSaved(false), 2500);
    } catch (e) { setSettingsErr((e as Error).message); }
    finally { setSettingsBusy(false); }
  };

  useEffect(() => { void load(); void loadSettings(); }, [load, loadSettings]);

  const testSms = async () => {
    setSmsBusy(true); setSms(null);
    try { setSms(await sendTestSms()); } catch (e) {
      setSms({ ok: false, delivered: false, dry_run: false, textbee_configured: false, phones_masked: [], statuses: [], attempts: [], reason: (e as Error).message });
    } finally { setSmsBusy(false); void load(); }
  };

  const falseAlarm = async (id: string) => {
    try { await markFalseAlarm(id); void load(); } catch (e) { setErr((e as Error).message); }
  };

  const removeRecipient = async (phone: string) => {
    setRemoveBusy(phone);
    try {
      const res = await removePhone(phone);
      if (!res.ok) { setErr(res.reason ?? "Could not remove recipient."); return; }
      setErr(null);
    } catch (e) { setErr((e as Error).message); }
    finally { setRemoveBusy(null); void load(); }
  };

  const rules = Object.entries(d?.sms.rules ?? {});
  const provText = Object.entries(d?.sms.provider_status ?? {}).filter(([p]) => p !== "log").map(([p, v]) => `${p}: ${v.status ?? "—"}`).join(" · ");

  return (
    <div className="flex flex-col gap-4">
      {err && <p role="status" className="rounded-xl border border-warn/40 bg-warn/10 p-3 text-sm text-warn">{err}</p>}
      <SmsSetup user={user} />

      <section aria-label="Test SMS" className="rounded-2xl border border-line bg-[var(--surface-1)] p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-[15px] font-semibold text-ink">Test the SMS route</h2>
            <p className="mt-0.5 text-[11px] text-mute">
              {d?.sms.phones_configured ? (
                <>
                  Recipients:{" "}
                  {d.sms.phones_masked.map((m, i) => (
                    <span key={i} className="flex items-center gap-1.5">
                      <span className="text-mute">{m}</span>
                      <button
                        onClick={() => void removeRecipient(m)}
                        disabled={removeBusy === m}
                        className="inline-flex h-5 w-5 items-center justify-center rounded border border-line bg-surface/50 text-xs text-mute hover:bg-warn/10 hover:text-warn disabled:opacity-50"
                        aria-label={`Remove ${m}`}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                  {provText ? ` · ${provText}` : ""}
                </>
              ) : "No verified phone yet — sign in again to register this number."}
            </p>
          </div>
          <button onClick={() => void testSms()} disabled={smsBusy}
            className="inline-flex h-9 items-center gap-2 rounded-lg border border-cyan/40 bg-[var(--surface-1)] px-3 text-sm font-medium text-cyan hover:bg-surface disabled:opacity-50">
            <Phone className="h-4 w-4" />{smsBusy ? "Sending…" : "Send test SMS"}
          </button>
        </div>
        {sms && (
          <p role="status" className={`mt-2 rounded-lg border p-2 text-[12px] ${sms.ok ? "border-ok/30 bg-ok/5 text-ok" : "border-warn/40 bg-warn/10 text-warn"}`}>
            {sms.ok ? "Test SMS sent. Check the registered phone." : `Not sent: ${sms.reason ?? sms.statuses.join(", ")}`}
            {sms.attempts.length > 0 && <span className="text-mute"> · attempts: {sms.attempts.map((a) => `${a.provider}:${a.status}`).join(", ")}</span>}
          </p>
        )}
      </section>

      <section aria-label="Alert rules" className="rounded-2xl border border-line bg-[var(--surface-1)] shadow-sm">
        <div className="border-b border-line p-4">
          <h2 className="text-[15px] font-semibold text-ink">Alert rules</h2>
          <p className="mt-0.5 text-[11px] text-mute">The SMS itself is sent in plain English so it is easy to read on any phone.</p>
        </div>
        <ul className="divide-y divide-line">
          {rules.map(([id, r]) => (
            <li key={id} className="flex flex-wrap items-center gap-2 px-4 py-2.5">
              <Badge tone="info">{id}</Badge>
              <span className="text-sm font-medium text-ink">{RULE_EN[id]?.label ?? r.label}</span>
              <span className="text-[11px] text-mute">{RULE_EN[id]?.hint}</span>
              <span className="ml-auto text-[11px] text-mute">{r.points} pts · cooldown {r.cooldown_min} min</span>
            </li>
          ))}
        </ul>
        <p className="border-t border-line p-4 text-[11px] text-mute">Rules are advisory and provisional. Pump and feeder control are never automated.</p>
      </section>

      <section aria-label="Cooldown settings" className="rounded-2xl border border-line bg-[var(--surface-1)] shadow-sm">
        <div className="border-b border-line p-4">
          <h2 className="text-[15px] font-semibold text-ink">Cooldown settings</h2>
          <p className="mt-0.5 text-[11px] text-mute">
            Set how long (in minutes) the same alert rule is suppressed after it fires. Set per rule to match your farm&rsquo;s
            response cadence. Changes persist on the server and take effect immediately.
          </p>
        </div>
        <div className="divide-y divide-line p-4">
          {Object.entries(d?.sms.rules ?? {}).map(([id, r]) => {
            const current = settings?.[id] ?? r.cooldown_min;
            return (
              <div key={id} className="flex flex-wrap items-center gap-2 px-2 py-2.5">
                <Badge tone="info">{id}</Badge>
                <span className="text-sm font-medium text-ink">{RULE_EN[id]?.label ?? r.label}</span>
                <span className="text-[11px] text-mute">{RULE_EN[id]?.hint}</span>
                <div className="ml-auto flex items-center gap-2">
                  <input
                    type="number"
                    min="1"
                    step="1"
                    value={String(current)}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      if (!Number.isNaN(v) && v >= 1) setSettings((prev) => ({ ...prev, [id]: v }));
                    }}
                    disabled={settingsBusy}
                    className="w-16 h-7 rounded border border-line bg-[var(--surface-1)] text-[11px] text-ink px-2 focus:border-cyan/60 disabled:opacity-50"
                    aria-label={`Cooldown minutes for ${id}`}
                  />
                  <span className="text-[10px] text-mute">min</span>
                </div>
              </div>
            );
          })}
        </div>
        <div className="p-4">
          <button
            onClick={() => void saveSettings()}
            disabled={settingsBusy || !settings}
            className="inline-flex h-9 items-center gap-2 rounded-lg border border-cyan/40 bg-[var(--surface-1)] px-3 text-sm font-medium text-cyan hover:bg-surface disabled:opacity-50"
          >
            {settingsBusy ? <span>Saving…</span> : <span>Save cooldowns</span>}
          </button>
          {settingsSaved && <span className="ml-2 text-[11px] text-success">Saved.</span>}
          {settingsErr && <p className="mt-1.5 text-[11px] text-warn">{settingsErr}</p>}
        </div>
      </section>

      <section aria-label="Alert history" className="rounded-2xl border border-line bg-[var(--surface-1)] shadow-sm">
        <div className="flex items-center justify-between gap-2 border-b border-line p-4">
          <div>
            <h2 className="text-[15px] font-semibold text-ink">Alert history</h2>
            <p className="mt-0.5 text-[11px] text-mute">Persisted on the server · false alarms feed future tuning</p>
          </div>
          <button onClick={() => void load()} disabled={busy} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line px-2.5 text-xs text-ink hover:bg-surface disabled:opacity-50">
            <RefreshCw className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} />Refresh
          </button>
        </div>
        {!d || d.alerts.length === 0 ? <p className="p-4 text-sm text-mute">No alerts yet.</p> : (
          <ul className="divide-y divide-line">
            {d.alerts.map((a) => (
              <li key={a.id} className="flex flex-col gap-1.5 px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={TONE(a.level)}>{a.level}</Badge>
                  <span className="text-sm font-semibold text-ink">{RULE_EN[a.rule]?.label ?? a.rule}</span>
                  <span className="text-[11px] text-mute">{new Date(a.t * 1000).toLocaleString()}</span>
                  <Badge tone={a.delivered ? "ok" : "mute"}>{a.delivered ? "SMS delivered" : "log only"}</Badge>
                  {a.false_alarm ? <Badge tone="mute">marked false alarm</Badge>
                    : <button onClick={() => void falseAlarm(a.id)} className="ml-auto text-[11px] text-cyan underline-offset-2 hover:underline">Not an alert?</button>}
                </div>
                <p className="text-[11px] text-mute">SMS text: {RULE_EN[a.rule]?.label ?? a.rule}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <p className="rounded-xl border border-line bg-[var(--surface-1)] p-3 text-[11px] text-mute">
        <Bell className="mr-1 inline h-3.5 w-3.5 text-cyan" />Only verified phones receive alerts. The SMS gateway phone must stay online with SMS balance.
      </p>
    </div>
  );
}
