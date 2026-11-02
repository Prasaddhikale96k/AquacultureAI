import type { Point, SensorKey, SensorStatus } from "../services/thingspeak";

/**
 * PROVISIONAL alert thresholds. Temperature, pH and dissolved-oxygen ranges are copied from the project's water_quality_config.json
 * (general tilapia screening values). They are NOT validated for any species, life stage or tank. Turbidity is a raw uncalibrated
 * sensor value, so it deliberately has no threshold. Edit here only: no component holds threshold numbers.
 */
export const THRESHOLDS: Partial<Record<SensorKey, { min?: number; max?: number; unit: string }>> = {
  temperature: { min: 25, max: 32, unit: "°C" },
  ph: { min: 6.5, max: 8.5, unit: "pH" },
  do: { min: 5, unit: "mg/L" },
};
export const LABELS: Record<SensorKey, string> = { temperature: "Water Temperature", turbidity: "Raw Turbidity (ADC)", ph: "pH", do: "Dissolved Oxygen" };
// Turbidity is the sensor's raw ADC count, uncalibrated: it is never presented as NTU.
export const UNITS: Record<SensorKey, string> = { temperature: "°C", turbidity: "ADC", ph: "pH", do: "mg/L" };

/** Share of the stale limit still remaining (100% = just measured, 0% = at or past the limit). Not a measure of sensor quality. */
export const freshness = (lastT: number | undefined, staleMs: number, now = Date.now()) =>
  lastT === undefined ? null : Math.max(0, Math.min(100, Math.round(100 * (1 - (now - lastT) / staleMs))));

/** One factual sentence about the fetched temperature window, or null with fewer than 2 valid readings. */
export function describeTemperature(points: Point[]): { text: string; detail: string } | null {
  if (points.length < 2) return null;
  const vs = points.map((p) => p.v), min = Math.min(...vs), max = Math.max(...vs), th = THRESHOLDS.temperature!;
  const outside = vs.filter((v) => v < th.min! || v > th.max!).length;
  const hm = (t: number) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  return {
    text: `In the last ${points.length} valid readings, water temperature stayed within ${min.toFixed(1)}–${max.toFixed(1)} °C.`,
    detail: `Derived from fetched ThingSpeak data only · window ${hm(points[0].t)}–${hm(points[points.length - 1].t)} · ${outside === 0 ? `all ${points.length}` : `${outside} of ${points.length}`} readings ${outside === 0 ? "fall inside" : "fall outside"} the provisional ${th.min}–${th.max} °C bounds`,
  };
}

export type CameraStatus = "off" | "starting" | "on" | "denied" | "unsupported" | "error";
export interface Alert {
  id: string; severity: "warning" | "info"; title: string; detail: string;
  observed?: string; threshold?: string; timestamp?: number; source: string;
}
export interface AlertInput {
  sensors: { key: SensorKey; status: SensorStatus; last?: Point; field: number | null }[];
  fetchError: string | null; configured: boolean;
  camera: CameraStatus; backendConnected: boolean; modelAvailable: boolean;
  visionBackend?: "api" | "yolo" | null;
  now?: number;
}

const age = (ms: number) => (ms < 90_000 ? `${Math.round(ms / 1000)} s` : ms < 5_400_000 ? `${Math.round(ms / 60000)} min` : `${(ms / 3_600_000).toFixed(1)} h`);

/** Rule-based alerts. A value is compared with a threshold only when it is a live valid reading; missing/stale data never triggers a numeric alert. */
export function buildAlerts(i: AlertInput): Alert[] {
  const out: Alert[] = [];
  const now = i.now ?? Date.now();
  if (!i.configured) out.push({ id: "ts-config", severity: "info", title: "ThingSpeak not configured", detail: "Set the channel ID in frontend/.env.local to read sensor data.", source: "Configuration" });
  if (i.fetchError) out.push({ id: "ts-fetch", severity: "warning", title: "ThingSpeak fetch failed", detail: i.fetchError, source: "ThingSpeak" });
  if (i.configured) for (const s of i.sensors) {
    const name = LABELS[s.key], core = s.key === "temperature" || s.key === "turbidity";
    if (s.status === "no_data") out.push({ id: `${s.key}-nodata`, severity: "info", title: `${name}: no data available`, detail: "A field is mapped but the channel has no valid readings for it.", source: "ThingSpeak" });
    else if (s.status === "not_configured" && core) out.push({ id: `${s.key}-nofield`, severity: "info", title: `${name}: field not configured`, detail: "No channel field was matched. Set the field number in frontend/.env.local.", source: "Configuration" });
    else if (s.status === "stale" && s.last) out.push({ id: `${s.key}-stale`, severity: "warning", title: `${name}: stale reading`, detail: `The newest valid measurement is ${age(now - s.last.t)} old${i.fetchError ? " and the latest refresh failed" : ""}.`, timestamp: s.last.t, source: "ThingSpeak" });
    const th = THRESHOLDS[s.key];
    if (s.status === "live" && s.last && th) {
      const v = s.last.v, low = th.min !== undefined && v < th.min, high = th.max !== undefined && v > th.max;
      if (low || high) out.push({
        id: `${s.key}-range`, severity: "warning", title: `${name} ${low ? "below" : "above"} provisional range`,
        detail: "Compared with an unvalidated screening range. This is not a diagnosis of fish health.",
        observed: `${v} ${th.unit}`, threshold: `${th.min ?? "–"} to ${th.max ?? "–"} ${th.unit}`, timestamp: s.last.t, source: "ThingSpeak",
      });
    }
  }
  const inactive = i.sensors.filter((s) => (s.key === "ph" || s.key === "do") && s.status === "not_configured");
  if (i.configured && inactive.length) out.push({ id: "ph-do-inactive", severity: "info", title: `${inactive.map((s) => LABELS[s.key]).join(" and ")} alert rules inactive`, source: "Sensor configuration",
    detail: "No field is configured for these metrics, so the rule exists but cannot evaluate yet. It activates once a field is mapped and returns data." });
  if (i.camera !== "on") out.push({ id: "camera", severity: "info", title: "Camera unavailable", source: "Browser camera", detail: ({
    off: "The camera is switched off.", starting: "The camera is starting.", denied: "Camera permission was denied in the browser.",
    unsupported: "This browser or page cannot access a camera (HTTPS or localhost is required).", error: "The camera could not be opened.",
  } as const)[i.camera] });
  if (!i.backendConnected) out.push({ id: "model", severity: "warning", title: "Model unavailable", detail: "The analysis backend is not reachable, so no detection can run.", source: "Backend" });
  else if (!i.modelAvailable) out.push({ id: "model", severity: "warning", title: "Model unavailable",
    detail: i.visionBackend === "yolo" ? "The backend is running but the model weights were not found."
      : "The backend is running but no LLM API key is configured (GROQ_API_KEY and/or GEMINI_API_KEY).", source: "Backend" });
  return out;
}
