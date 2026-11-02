import type { AdviceResponse, AlertItem, AlertsPayload, AuthLoginResult, AuthMeResult, AuthStatus, AuthUser, AuthVerifyResult, AnalysisResult, BehaviorObservation, BehaviorStatsData, BehaviourSummary, CombinedAssessment, DashboardData, DoPrediction, ExplanationResponse, FeedingSummary, HistoryRecord, JobStatus, LiveResult, LlmStatus, Predictions, RiskDocument, TestSmsResult, TrackSummary, VisionStatus, WaterAssessment, WaterConfig, WaterPayload, WaterReading, WaterRecord } from "../types";
import { HISTORICAL_WATER, WATER_THRESHOLDS } from "./historical";

/**
 * Backend contract (implemented by backend/main.py; routes are relative to VITE_API_BASE_URL):
 *   GET  /health                                  -> { status, model_available, model_validated }
 *   POST /api/videos           (multipart "file") -> { jobId, videoId, status: "uploaded" }
 *   POST /api/analyses         { videoId }        -> { jobId, status: "queued" }  (409 if queued/running/completed)
 *   GET  /api/analyses/{id}                       -> { state: uploaded|queued|processing|completed|failed, error? }
 *   GET  /api/analyses/{id}/results               -> AnalysisResult (409 until completed)
 *   GET  /api/analyses/{id}/frames/{original|annotated} -> image/jpeg
 *   GET  /health                                    -> { status, model_available, vision_backend, ... }
 *   GET  /api/vision-status                         -> { backend: api|yolo, groq_model, gemini_chain, ... }
 *   GET  /api/tracks                                -> { tracks: TrackSummary[] }
 *   POST /api/behavior          { trackId }          -> { provider, model, observation, ... }
 *   GET  /api/llm-status                            -> { groq_configured, gemini_configured, groq_model, gemini_model, fallback_order }
 *   POST /api/advice            { tankId, jobId? }   -> { provider, model, advice, fallback_used, tried, waterRisk, overallStatus }
 *   POST /api/risk              { tankId, jobId? }   -> RiskDocument (NORMAL/WATCH/WARNING/CRITICAL/INSUFFICIENT_DATA)
 *   POST /api/explanation       { tankId, jobId? }   -> ExplanationResponse (structured JSON, cached, cooldown)
 *   GET  /api/history?limit=&event=                  -> { records: HistoryRecord[] }
 */
// Development default only; set VITE_API_BASE_URL for any other environment. Production builds have no default.
// In dev, "" keeps API calls relative to the dev-server origin so the vite
// /api proxy (same-origin) forwards them to the backend and HttpOnly session
// cookies (SameSite=Lax) are sent on every request.
const BASE = ((import.meta.env.VITE_API_BASE_URL as string | undefined) ?? (import.meta.env.DEV ? "" : "")).replace(/\/$/, "");
// In dev the vite /api proxy forwards to the backend, so a backend is reachable
// even though BASE is relative (same-origin) for cookie delivery.
export const backendConfigured = BASE !== "" || import.meta.env.DEV;
export const MAX_UPLOAD_MB = Number(import.meta.env.VITE_MAX_UPLOAD_MB ?? 500);
export const ACCEPTED_EXT = [".mp4", ".mov", ".avi", ".mkv", ".webm"];

export const assetUrl = (path?: string) => (!path ? undefined : /^(https?:|blob:|data:)/.test(path) ? path : BASE + path);

export const AUTH_EVENT = "aqua:unauthorized";
export const AUTH_USER_KEY = "aqua_user";

function csrfToken(): string | null {
  const match = document.cookie.match(/(?:^|;\s*)aqua_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

function requestInit(init: RequestInit = {}): RequestInit {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const token = csrfToken();
    if (token) headers.set("X-CSRF-Token", token);
  }
  return { ...init, headers, credentials: "include" };
}

function unauthorized(res: Response): void {
  if (res.status === 401 && typeof window !== "undefined") window.dispatchEvent(new Event(AUTH_EVENT));
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, requestInit(init));
  if (!res.ok) {
    unauthorized(res);
    const detail = await res.json().then((j: { error?: string; reason?: string }) => j.error ?? j.reason, () => undefined);
    throw new Error(detail ?? `${init?.method ?? "GET"} ${path} failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export function validateVideo(file: File): string | null {
  const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (!ACCEPTED_EXT.includes(ext) || (file.type && !file.type.startsWith("video/")))
    return `Unsupported file. Use ${ACCEPTED_EXT.join(", ")}.`;
  if (file.size === 0) return "The file is empty.";
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return `File is larger than ${MAX_UPLOAD_MB} MB.`;
  return null;
}

export const checkHealth = async (): Promise<{ modelAvailable: boolean; visionBackend?: "api" | "yolo" }> => {
  const res = await fetch(BASE + "/health");
  if (!res.ok) throw new Error("unhealthy");
  const j = (await res.json()) as { status?: string; model_available?: boolean; vision_backend?: "api" | "yolo" };
  if (j.status !== "ok") throw new Error("unhealthy");
  return { modelAvailable: j.model_available === true, visionBackend: j.vision_backend };
};

export function uploadVideo(file: File, onProgress: (p: number) => void, signal: AbortSignal): Promise<{ videoId: string }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", BASE + "/api/videos");
    xhr.withCredentials = true;
    const token = csrfToken();
    if (token) xhr.setRequestHeader("X-CSRF-Token", token);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      if (xhr.status < 300) return resolve(JSON.parse(xhr.responseText));
      let detail = "";
      try { detail = JSON.parse(xhr.responseText).error ?? ""; } catch { /* non-JSON error body */ }
      reject(new Error(detail || `Upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("Upload failed: network error"));
    signal.addEventListener("abort", () => { xhr.abort(); reject(new DOMException("Cancelled", "AbortError")); });
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export const startAnalysis = (videoId: string) =>
  json<{ jobId: string }>("/api/analyses", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ videoId }) });
export const getJobStatus = (jobId: string) => json<JobStatus>(`/api/analyses/${jobId}`);
export const getAnalysisResult = (jobId: string) => json<AnalysisResult>(`/api/analyses/${jobId}/results`);

/** One frame -> frame-level detections from the existing weights (POST /api/live/detect). Boxes/outlines are normalised 0-1. */
export type { LiveDetection, LiveMovement, LiveRejected, LiveResult, LiveTrack } from "../types";
export const detectFrame = (frame: Blob, signal: AbortSignal) =>
  json<LiveResult>("/api/live/detect", { method: "POST", headers: { "Content-Type": "image/jpeg" }, body: frame, signal });
/** One frame -> detections + session-local tracks + movement summary (POST /api/live/track?session=...). */
export const trackFrame = (frame: Blob, session: string, signal: AbortSignal) =>
  json<LiveResult>(`/api/live/track?session=${encodeURIComponent(session)}`, { method: "POST", headers: { "Content-Type": "image/jpeg" }, body: frame, signal });

const LABELS = {
  temperature: ["Temperature", "°C"], turbidity: ["Turbidity", "NTU"], pH: ["pH", ""], do: ["Dissolved Oxygen", "mg/L"],
} as const;

/** No live sensor service exists yet, so this always returns the project's historical metadata, labelled as such. */
export async function getWaterQuality(): Promise<{ readings: WaterReading[]; live: boolean }> {
  const readings = (Object.keys(LABELS) as (keyof typeof LABELS)[]).map((key): WaterReading => {
    const series = HISTORICAL_WATER.map((r) => ({ t: r.t, v: r[key] }));
    const last = HISTORICAL_WATER[HISTORICAL_WATER.length - 1];
    return { key, label: LABELS[key][0], unit: LABELS[key][1], value: last[key], timestamp: last.t, source: "historical", series, range: WATER_THRESHOLDS[key] };
  });
  return { readings, live: false };
}

// ---- water-quality input + assessment (rules run on the backend)
export class FieldError extends Error {
  constructor(message: string, public fields: Record<string, string> = {}) { super(message); }
}
export const getWaterConfig = () => json<WaterConfig>("/api/water-config");
export const getWaterHistory = (tankId?: string) =>
  json<{ tanks: string[]; readings: WaterRecord[]; skippedLines: number }>(`/api/water-readings${tankId ? `?tankId=${encodeURIComponent(tankId)}` : ""}`);
export const getWaterAssessment = (tankId: string) => json<WaterAssessment>(`/api/water-assessment?tankId=${encodeURIComponent(tankId)}`);
export const getCombinedAssessment = (tankId: string, jobId?: string | null) =>
  json<CombinedAssessment>(`/api/assessment?tankId=${encodeURIComponent(tankId)}${jobId ? `&jobId=${jobId}` : ""}`);
export async function submitWaterReading(p: WaterPayload): Promise<{ reading: WaterRecord; assessment: WaterAssessment }> {
  const res = await fetch(BASE + "/api/water-readings", requestInit({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(p) }));
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    unauthorized(res);
    throw new FieldError(body.error ?? body.reason ?? `Save failed (${res.status})`, body.fields);
  }
  return body;
}

// ---- Unified risk + structured explanation + history (Â§7, Â§8.2/Â§8.3, Â§10F)
async function postJson<T>(path: string, payload: unknown): Promise<T> {
  const res = await fetch(BASE + path, requestInit({
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  }));
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    unauthorized(res);
    const err = (body as { error?: string; reason?: string; retry_after_s?: number }).error
      ?? (body as { reason?: string }).reason ?? `${path} failed (${res.status})`;
    const e = new Error(err) as Error & { retryAfterS?: number; last?: unknown };
    if (typeof (body as { retry_after_s?: unknown }).retry_after_s === "number") {
      e.retryAfterS = (body as { retry_after_s?: number }).retry_after_s;
      e.last = (body as { last?: unknown }).last;
    }
    throw e;
  }
  return body as T;
}
export const getRisk = (tankId: string, jobId?: string | null) =>
  postJson<RiskDocument>("/api/risk", { tankId, ...(jobId ? { jobId } : {}) });
export const getExplanation = (tankId: string, jobId?: string | null) =>
  postJson<ExplanationResponse>("/api/explanation", { tankId, ...(jobId ? { jobId } : {}) });
export const getHistory = (limit = 50, event?: string) =>
  json<{ records: HistoryRecord[]; skippedLines: number }>(
    `/api/history?limit=${limit}${event ? `&event=${encodeURIComponent(event)}` : ""}`);
// ---- API vision status, tracks and LLM behavior (replaces YOLO weights + RandomForest)
export const getVisionStatus = () => json<VisionStatus>("/api/vision-status");
export const getTracks = () => json<{ tracks: TrackSummary[] }>("/api/tracks");
export async function getBehavior(trackId: number, inlineTrack?: Record<string, unknown>): Promise<BehaviorObservation> {
  const res = await fetch(BASE + "/api/behavior", requestInit({
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(inlineTrack ? { track: inlineTrack } : { trackId }),
  }));
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    unauthorized(res);
    throw new Error((body as { error?: string; reason?: string }).error ?? (body as { reason?: string }).reason ?? `Behavior failed (${res.status})`);
  }
  return body as BehaviorObservation;
}
// ---- LLM advice: Groq primary, Gemini fallback (keys stay on the backend; the
// model only explains the already-computed rule-based assessment)
export const getLlmStatus = () => json<LlmStatus>("/api/llm-status");
export async function getAdvice(tankId: string, jobId?: string | null): Promise<AdviceResponse> {
  const res = await fetch(BASE + "/api/advice", requestInit({
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tankId, ...(jobId ? { jobId } : {}) }),
  }));
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    unauthorized(res);
    throw new Error((body as { error?: string; reason?: string }).error ?? (body as { reason?: string }).reason ?? `Advice failed (${res.status})`);
  }
  return body as AdviceResponse;
}
// ---- Farmer finalization: alerts, dashboard, predictions, behaviour windows
export const getAlerts = (limit = 50) => json<AlertsPayload>(`/api/alerts?limit=${limit}`);
export const getDashboard = () => json<DashboardData>("/api/dashboard");
export const getPredictions = () => json<Predictions>("/api/predictions");
export const getBehaviorStats = () => json<BehaviorStatsData>("/api/behavior-stats");
export const getDoPrediction = () => json<DoPrediction>("/api/do-prediction");
export const getBehaviourSummary = () => json<BehaviourSummary>("/api/behaviour/summary");
export const getFeedingSummary = () => json<FeedingSummary>("/api/feeding");
export const sendTestSms = () => postJson<TestSmsResult>("/api/alerts/test", {});
export const removePhone = (phone: string) =>
  postJson<{ ok: boolean; phone_masked?: string; reason?: string }>("/api/auth/remove-phone", { phone });
export const markFalseAlarm = (id: string, note?: string) =>
  postJson<{ marked: boolean }>("/api/alerts/false-alarm", { id, ...(note ? { note } : {}) });
export const getAlertSettings = () => json<{ cooldown_min: Record<string, number> }>("/api/alerts/settings");
export const putAlertSettings = (cooldownMin: Record<string, number>) =>
  json<{ cooldown_min: Record<string, number> }>("/api/alerts/settings", {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ cooldown_min: cooldownMin }),
  });
export type { AlertItem };


export const getAuthStatus = () => json<AuthStatus>("/api/auth/status");

async function authPost<T extends { ok: boolean; reason?: string }>(path: string, payload: unknown): Promise<T> {
  const res = await fetch(BASE + path, requestInit({
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  }));
  const body = (await res.json().catch(() => ({}))) as T & { error?: string };
  if (!res.ok) return { ...body, ok: false, reason: body.reason ?? body.error ?? `Request failed (${res.status})` };
  return body;
}

export const authLogin = (phone: string) => authPost<AuthLoginResult>("/api/auth/login", { phone });
export const authResend = (phone: string) => authPost<AuthLoginResult>("/api/auth/resend", { phone });
export const authVerify = (phone: string, otp: string) => authPost<AuthVerifyResult>("/api/auth/verify", { phone, otp });
export const authRegister = (profile: {
  name: string; phone: string; tankId: string; species: string; system: string;
}) => authPost<AuthLoginResult>("/api/auth/register", profile);

export async function authMe(): Promise<AuthUser | null> {
  try {
    const res = await fetch(BASE + "/api/auth/me", requestInit());
    if (!res.ok) return null;
    const body = (await res.json()) as AuthMeResult;
    return body.ok ? body.user ?? null : null;
  } catch {
    return null;
  }
}

export async function authLogout(): Promise<void> {
  try {
    await fetch(BASE + "/api/auth/logout", requestInit({ method: "POST" }));
  } catch {
    /* local logout still proceeds */
  } finally {
    localStorage.removeItem(AUTH_USER_KEY);
  }
}
