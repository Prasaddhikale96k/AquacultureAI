import { AlertTriangle, Bell, Info } from "lucide-react";
import { SENSOR_KEYS, statusOf } from "../services/thingspeak";
import type { Sensors } from "../hooks/useSensors";
import { buildAlerts, type Alert, type CameraStatus } from "../config/alerts";
import { Badge } from "../components/ui";
import type { StatusItem } from "../components/Shell";

export interface Integration { backendConnected: boolean; modelAvailable: boolean; camera: CameraStatus; inferring: boolean; visionBackend?: "api" | "yolo" | null }
const card = "rounded-2xl border border-line bg-[var(--surface-1)] shadow-[0_1px_2px_rgb(20_23_28/0.04),0_8px_24px_-16px_rgb(20_23_28/0.12)]";

/** Honest ThingSpeak status: "Connected" only after a request succeeded, and "No Recent Data" when nothing is fresh. */
export function thingSpeakStatus(s: Sensors): StatusItem {
  if (s.problem) return { label: "ThingSpeak", value: "Not Configured", tone: "mute" };
  if (s.error) return { label: "ThingSpeak", value: "Fetch Failed", tone: "bad" };
  if (!s.readings || !s.mapping) return { label: "ThingSpeak", value: "Connecting…", tone: "mute" };
  const live = SENSOR_KEYS.some((k) => statusOf(s.readings![k], s.mapping![k].field, true) === "live");
  return live ? { label: "ThingSpeak", value: "Connected", tone: "ok" } : { label: "ThingSpeak", value: "No Recent Data", tone: "warn" };
}
export const cameraStatus = (c: CameraStatus): StatusItem => ({ label: "Camera", tone: c === "on" ? "ok" : c === "starting" ? "mute" : "warn",
  value: { on: "On", off: "Off", starting: "Starting…", denied: "Permission denied", unsupported: "Unavailable", error: "Unavailable" }[c] });
export const modelStatus = (i: Integration): StatusItem => {
  const label = i.visionBackend === "yolo" ? "YOLO model" : "API vision";
  if (i.modelAvailable && i.backendConnected)
    return { label, value: i.inferring ? "Responding (unvalidated)" : i.visionBackend === "yolo" ? "Weights present" : "Groq/Gemini ready", tone: i.inferring ? "ok" : "mute" };
  return { label, value: i.backendConnected ? (i.visionBackend === "yolo" ? "Weights missing" : "API keys missing") : "Backend offline", tone: "warn" };
};

export function AlertPanel({ s, i }: { s: Sensors; i: Integration }) {
  const alerts: Alert[] = buildAlerts({
    configured: !s.problem, fetchError: s.error, camera: i.camera, backendConnected: i.backendConnected, modelAvailable: i.modelAvailable,
    visionBackend: i.visionBackend,
    // Before the first successful fetch there is nothing to judge, so no per-sensor alert is raised.
    sensors: !s.readings ? [] : SENSOR_KEYS.map((k) => {
      const pts = s.readings![k], field = s.mapping![k].field;
      return { key: k, field, last: pts.at(-1), status: statusOf(pts, field, !s.error) };
    }),
  });
  const warnings = alerts.filter((a) => a.severity === "warning").length;
  return (
    <section aria-label="Alerts" className={`${card} p-4`}>
      <header className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-semibold text-ink">Alerts</h2>
          <p className="mt-0.5 text-[11px] text-mute">Rule-based, from one central threshold config. Staleness compares the newest <b>valid measurement</b>, never the last fetch attempt.</p>
        </div>
        <Badge tone={warnings ? "warn" : "mute"}>{warnings ? `${warnings} warning${warnings > 1 ? "s" : ""}` : "No warnings"}</Badge>
      </header>
      {alerts.length === 0 ? <p className="mt-3 text-sm text-mute">No rule is currently triggered. This is not a guarantee that conditions are safe.</p> : (
        <ul className="mt-3 divide-y divide-line" aria-label="Alert list">
          {alerts.map((a) => (
            <li key={a.id} className={`flex gap-3 border-l-2 py-2.5 pl-3 ${a.severity === "warning" ? "border-warn" : "border-brand"}`}>
              {a.severity === "warning" ? <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warn" /> : <Info className="mt-0.5 h-4 w-4 shrink-0 text-brand" />}
              <div className="min-w-0">
                <p className="text-sm font-semibold text-ink">{a.title}</p>
                <p className="text-xs text-mute">{a.detail}</p>
                <p className="mt-0.5 text-[10px] text-mute">
                  {a.observed && <>Observed {a.observed} {"·"} </>}{a.threshold && <>Provisional range {a.threshold} {"·"} </>}{a.timestamp && <>{new Date(a.timestamp).toLocaleString()} {"·"} </>}Source: {a.source}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 border-t border-line pt-2 text-[10px] text-mute">Default thresholds are provisional: they need validation for the actual species, tank and conditions. Alerts only report values outside a provisional range or data that is not arriving; water data alone cannot diagnose fish disease.</p>
    </section>
  );
}

export function SystemActivity({ s }: { s: Sensors }) {
  return (
    <section aria-label="System activity" className={`${card} p-4`}>
      <h2 className="flex items-center gap-2 text-[15px] font-semibold text-ink"><Bell className="h-4 w-4 text-brand" />System Activity</h2>
      <p className="text-[11px] text-mute">Read-only log generated by the app itself</p>
      {s.activity.length === 0 ? <p className="mt-3 text-xs text-mute">No activity yet.</p> : (
        <ul className="mt-3 max-h-56 space-y-2 overflow-auto pr-1">
          {s.activity.map((a, n) => (
            <li key={`${a.t}-${n}`} className={`rounded-xl border p-2.5 text-xs ${a.tone === "warn" ? "border-warn/30 bg-warn/5" : "border-line bg-surface"}`}>
              <p className="flex justify-between gap-2 text-ink"><span>{a.text}</span><span className="shrink-0 text-[10px] text-mute">{new Date(a.t).toLocaleTimeString([], { hour12: false })}</span></p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
