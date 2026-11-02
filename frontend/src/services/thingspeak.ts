// Read-only ThingSpeak client. Never writes to the channel and never takes a Write API key.
// NOTE: VITE_* variables are bundled into the browser build, so the Read API key is visible to anyone who can load the page.
export type SensorKey = "temperature" | "turbidity" | "ph" | "do";
export const SENSOR_KEYS: SensorKey[] = ["temperature", "turbidity", "ph", "do"];
export interface Point { t: number; v: number; id?: number }   // id = ThingSpeak entry_id
export type Reading = Record<SensorKey, Point[]>;
export interface FieldMap { field: number | null; source: "env" | "label" | "none"; label?: string }
export type Mapping = Record<SensorKey, FieldMap>;
export interface ThingSpeakConfig {
  channelId: string; readKey: string; results: number; staleMs: number; pollMs: number;
  fields: Record<SensorKey, number | null>;
}

const env: Record<string, unknown> = import.meta.env ?? {};
const field = (v: unknown) => { const n = Number(v); return v !== undefined && v !== "" && Number.isInteger(n) && n >= 1 && n <= 8 ? n : null; };
const positive = (v: unknown, d: number) => { const n = Number(v); return v !== undefined && v !== "" && Number.isFinite(n) && n > 0 ? n : d; };

export const CONFIG: ThingSpeakConfig = {
  channelId: String(env.VITE_THINGSPEAK_CHANNEL_ID ?? "").trim(),
  readKey: String(env.VITE_THINGSPEAK_READ_API_KEY ?? "").trim(),
  results: Math.min(positive(env.VITE_THINGSPEAK_RESULTS, 60), 8000),
  staleMs: positive(env.VITE_THINGSPEAK_STALE_MINUTES, 5) * 60_000,
  pollMs: Math.max(5, positive(env.VITE_THINGSPEAK_POLL_SECONDS, 5)) * 1000,   // never faster than every 5 s
  // An explicit field number always wins. Without one, the field is matched by the channel's own field label (see inferField).
  fields: {
    temperature: field(env.VITE_THINGSPEAK_FIELD_TEMPERATURE), turbidity: field(env.VITE_THINGSPEAK_FIELD_TURBIDITY),
    ph: field(env.VITE_THINGSPEAK_FIELD_PH), do: field(env.VITE_THINGSPEAK_FIELD_DO),
  },
};

// DS18B20 returns -127 on a bus error and 85 on power-up reset; neither is a real water temperature.
const SENTINELS: Partial<Record<SensorKey, number[]>> = { temperature: [-127, 85] };
const LABEL: Record<SensorKey, RegExp> = {
  temperature: /temp/i, turbidity: /turb/i, ph: /(^|[^a-z])ph([^a-z]|$)/i, do: /dissolved|oxygen|(^|[^a-z])do([^a-z]|$)/i,
};

/** Convert one raw ThingSpeak field value to a number, or null if missing/invalid. Null/blank is never 0. */
export function parseValue(raw: unknown, key: SensorKey): number | null {
  if (raw === null || raw === undefined || (typeof raw === "string" && raw.trim() === "")) return null;
  const n = typeof raw === "number" ? raw : Number(raw);
  if (!Number.isFinite(n) || SENTINELS[key]?.includes(n)) return null;
  return n;
}

/** Field labels from feeds.json `channel` ({field1: "Temperature", ...}). */
const labelsOf = (body: unknown): Record<number, string> => {
  const ch = (body as { channel?: Record<string, unknown> })?.channel ?? {};
  const out: Record<number, string> = {};
  for (let i = 1; i <= 8; i++) if (typeof ch[`field${i}`] === "string") out[i] = ch[`field${i}`] as string;
  return out;
};

/** Env field numbers win; otherwise a field is chosen only if exactly one label matches. Inferred mappings must be verified by the user. */
export function resolveMapping(body: unknown, cfg: ThingSpeakConfig = CONFIG): Mapping {
  const labels = labelsOf(body);
  const map = {} as Mapping;
  for (const key of SENSOR_KEYS) {
    const explicit = cfg.fields[key];
    if (explicit !== null) { map[key] = { field: explicit, source: "env", label: labels[explicit] }; continue; }
    const hits = Object.entries(labels).filter(([, l]) => LABEL[key].test(l));
    map[key] = hits.length === 1 ? { field: Number(hits[0][0]), source: "label", label: hits[0][1] } : { field: null, source: "none" };
  }
  return map;
}

/** Validate a feeds.json body and extract points (oldest first). Throws on a malformed body. */
export function parseFeeds(body: unknown, cfg: ThingSpeakConfig = CONFIG, now = Date.now()): { readings: Reading; mapping: Mapping; rejected: number } {
  const feeds = (body as { feeds?: unknown })?.feeds;
  if (!Array.isArray(feeds)) throw new Error("Unexpected response from ThingSpeak (no feeds list).");
  const mapping = resolveMapping(body, cfg);
  const readings: Reading = { temperature: [], turbidity: [], ph: [], do: [] };
  let rejected = 0;
  for (const f of feeds as Record<string, unknown>[]) {
    const t = Date.parse(String(f?.created_at ?? ""));
    if (!Number.isFinite(t) || t > now + 5 * 60_000) { rejected++; continue; }
    for (const key of SENSOR_KEYS) {
      const n = mapping[key].field;
      if (n === null) continue;
      const raw = f[`field${n}`];
      const v = parseValue(raw, key);
      if (v === null) { if (raw !== null && raw !== undefined && String(raw).trim() !== "") rejected++; continue; }
      const id = Number(f.entry_id);
      readings[key].push({ t, v, ...(Number.isInteger(id) && id > 0 ? { id } : {}) });
    }
  }
  for (const key of SENSOR_KEYS) readings[key].sort((a, b) => a.t - b.t);
  return { readings, mapping, rejected };
}

/** Why the integration cannot run, or null when configured. */
export function configProblem(cfg: ThingSpeakConfig = CONFIG): string | null {
  if (!cfg.channelId) return "Set VITE_THINGSPEAK_CHANNEL_ID in frontend/.env.local.";
  if (!/^\d+$/.test(cfg.channelId)) return "VITE_THINGSPEAK_CHANNEL_ID must be a number.";
  return null;
}

export async function fetchReadings(signal: AbortSignal, cfg: ThingSpeakConfig = CONFIG): Promise<ReturnType<typeof parseFeeds>> {
  const url = new URL(`https://api.thingspeak.com/channels/${cfg.channelId}/feeds.json`);
  url.searchParams.set("results", String(cfg.results));
  if (cfg.readKey) url.searchParams.set("api_key", cfg.readKey);
  let res: Response;
  try { res = await fetch(url, { signal }); }
  catch (e) { if ((e as Error).name === "AbortError") throw e; throw new Error("Network error: could not reach ThingSpeak."); }
  // Error messages never include the URL, so the key cannot leak into the UI.
  if (res.status === 400 || res.status === 404) throw new Error(`ThingSpeak refused the request (HTTP ${res.status}). For a private channel, check the channel ID and Read API key.`);
  if (!res.ok) throw new Error(`ThingSpeak returned HTTP ${res.status}.`);
  let body: unknown;
  try { body = await res.json(); } catch { throw new Error("ThingSpeak returned a response that is not valid JSON."); }
  return parseFeeds(body, cfg);
}

export type SensorStatus = "live" | "stale" | "no_data" | "not_configured";
/** live = newest valid reading is recent AND the last refresh succeeded; stale otherwise. */
export function statusOf(points: Point[], field: number | null, refreshOk: boolean, cfg: ThingSpeakConfig = CONFIG, now = Date.now()): SensorStatus {
  if (field === null) return "not_configured";
  if (points.length === 0) return "no_data";
  return refreshOk && now - points[points.length - 1].t <= cfg.staleMs ? "live" : "stale";
}
