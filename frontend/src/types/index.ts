export type DataSource = "live" | "historical" | "demo" | "unavailable";
export type BackendState = "demo" | "connecting" | "connected" | "unreachable";
export type JobState = "uploaded" | "queued" | "processing" | "completed" | "failed";

export interface VideoMeta {
  name: string;
  sizeBytes: number;
  durationSec?: number;
  width?: number;
  height?: number;
  posterUrl?: string; // first frame extracted locally in the browser
}

export interface JobStatus {
  state: JobState;
  progress?: number; // 0-1, only if the backend reports it
  error?: string;
}

/** Quality-gated analysis result. Every field is optional: absent means "not reported by the backend". */
export interface LiveDetection { box: [number, number, number, number]; confidence: number; outline?: [number, number][] }
export interface LiveRejected { box: [number, number, number, number]; confidence: number; reason: string }
export interface TrackBehavior {
  state: "normal_swimming" | "resting" | "resting_bottom" | "surface_gasping" | "surface_swimming" | "erratic" | "tracking";
  label: string;
  zone: "surface" | "midwater" | "bottom";
  zone_label?: string;
  tone: "ok" | "warn" | "bad" | "info" | "mute";
}
export interface LiveTrack { id: number; observations: number; duration_sec: number; mean_speed_px_sec: number | null; last_seen_sec_ago: number; confidence: number;
  confirmed?: boolean; static?: boolean; box?: [number, number, number, number];
  behavior?: TrackBehavior;
}
export interface LiveBehavior {
  overall_state: string;
  overall_label: string;
  status_tone: "ok" | "warn" | "bad" | "info" | "mute";
  detail: string;
  surface_proxy_pct: number;
  activity_level: string;
  schooling_state?: string;
  active_fish_count: number;
}
export interface LiveMovement {
  track_count: number; valid_speed_intervals: number; gaps_skipped: number;
  mean_speed_px_sec: number | null; stationary_frac: number | null; still_threshold_px_sec: number;
  camera: { state: "still" | "moving" | "unknown"; shift_frac: number; response: number };
  speeds_approximate: boolean; experimental: boolean; note: string;
}
export interface LiveResult { detections: LiveDetection[]; count: number; inferenceMs: number; timestamp: string; validated: false; note: string;
  vision?: { backend: "api" | "yolo"; provider?: string; model?: string };
  visionBackend?: "api" | "yolo" | "yolo-fallback(api-down)";
  degraded?: boolean; degradedReason?: string | null;
  rejected?: LiveRejected[]; review?: string;
  tracks?: LiveTrack[]; movement?: LiveMovement; behavior?: LiveBehavior; session?: { id: string; frames_processed: number; session_sec: number } }
export interface VisionBackendInfo {
  backend: "api" | "yolo"; providers?: string[]; sampling?: string;
  fallback_used?: boolean; masks?: boolean;
}
export interface AnalysisResult {
  videoName: string;
  fps?: number;
  frames?: number;
  processingSec?: number;
  visionBackend?: VisionBackendInfo;
  detections?: { meanPerFrame: number; min?: number; max?: number; framesWithoutDetection?: number; reliable?: boolean; reasons?: string[] };
  tracking?: { reliable: boolean; tracks?: number; flaggedForReview?: number; reasons?: string[] };
  movement?: { reliable: boolean; meanMaskAreaFrac?: number; meanBoxAreaFrac?: number; countChangeRate?: number; cameraDriftDiagonals?: number; reasons?: string[] };
  preview?: { originalUrl?: string; annotatedUrl?: string; timestampSec?: number; detections?: number; quality?: string; confidences?: number[] };
  processing?: { framesProcessed: number; framesTotal: number; sampling: string; previewFrameIndex: number; previewNote: string };
  reliability?: { detections?: VideoState; movement?: VideoState; tracking?: VideoState };
  counts?: { kind: string; uniqueFish: number | null };
  observations?: Observation[];
  warnings?: string[];
}

export type ObservationCategory = "Detection Quality" | "Tracking Quality" | "Movement Observation" | "Water Quality";
export interface Observation {
  category: ObservationCategory;
  severity: "info" | "warning" | "error" | "ok";
  title: string;
  detail: string;
  timestamp?: string;
  reliability?: number; // only when supplied by the analysis (0-1)
  kind: "measured" | "preliminary";
}

export interface WaterReading {
  key: "temperature" | "turbidity" | "pH" | "do";
  label: string;
  unit: string;
  value?: number;
  timestamp?: string;
  source: DataSource;
  series: { t: string; v: number }[];
  range?: { min: number | null; max: number | null };
}

export type AnalysisStatus = "completed" | "processing" | "failed" | "needs_review" | "not_analyzed";
export interface RecentAnalysis {
  id: string;
  filename: string;
  at: string;
  durationSec?: number;
  status: AnalysisStatus;
  thumbnailUrl?: string;
  source: "session" | "backend" | "demo";
}

// ---- water-quality input and rule-based assessment (computed by the backend; nothing is calculated in the browser)
export type MeasurementKey = "temperature" | "pH" | "dissolvedOxygen" | "turbidity" | "ammonia" | "nitrite" | "nitrate" | "salinity";
export type Level = "normal" | "warning" | "high_concern" | "critical_concern" | "insufficient_data" | "not_assessed";
export type WaterRisk = "critical_concern" | "high_concern" | "warning" | "no_rule_triggered" | "insufficient_data";
export type InputSource = "manual" | "sensor" | "imported_historical";

export interface WaterConfig {
  options: { species: string[]; lifeStage: string[]; system: string[]; source: InputSource[]; ammoniaMethod: string[] };
  units: Record<MeasurementKey, string[]>;
  canonicalUnits: Record<MeasurementKey, string>;
  plausible: Record<MeasurementKey, [number, number]>;
  rulesStatus: string;
}

export interface WaterPayload {
  tankId: string; species: string; lifeStage: string | null; system: string; timestamp: string; source: InputSource; supersedes?: string | null;
  measurements: Partial<Record<MeasurementKey, { value: number; unit: string; method?: string }>>;
}

export interface WaterRecord extends WaterPayload {
  id: string; createdAt: string; superseded?: boolean;
  measurements: Partial<Record<MeasurementKey, { value: number; unit: string; method?: string; canonicalValue: number }>>;
}

export interface MeasurementAssessment {
  parameter: MeasurementKey; label: string; unit: string; level: Level;
  dataQuality: "ok" | "missing" | "stale" | "invalid" | "contradictory";
  value: number | null; enteredValue?: number; enteredUnit?: string; timestamp?: string; source?: InputSource; method?: string;
  message: string; check: string[]; actions: string[];
  rule: { id: string; direction: string; threshold: number; band: string; provisional: boolean } | null;
  confirmed: boolean | null; persistence: number;
}

export interface WaterAssessment {
  tankId: string; species: string; system: string; lifeStage: string | null; generatedAt: string; rulesStatus: string; kind: "rule_based_screening";
  profile: string | null; lifeStageNote: string | null; measurements: MeasurementAssessment[]; concerns: MeasurementAssessment[];
  concernGroups: { group: string; level: Level; parameters: string[] }[]; notes: string[]; waterRisk: WaterRisk; summary: string;
  dataQuality: { status: "sufficient" | "partial" | "insufficient"; missing: string[]; stale: string[]; contradictory: string[]; coreMissingOrUnusable: string[] };
}

export type VideoState = "reliable" | "needs_review" | "unreliable" | "unavailable";
export interface VideoSummary {
  available: boolean; reason?: string; videoName?: string; usedInRisk: false; observations?: string[];
  reliability?: { detections?: VideoState; movement?: VideoState; tracking?: VideoState };
}
export interface CombinedAssessment {
  water: WaterAssessment | null; video: VideoSummary; overallStatus: "action_recommended" | "review_recommended" | "no_rule_triggered" | "insufficient_data";
  dataQuality: { water: string; video: string }; uncertainty: string[]; crossNotes: string[];
}

// ---- Unified operational risk (§7): deterministic 5-level taxonomy
export type RiskStatus = "NORMAL" | "WATCH" | "WARNING" | "CRITICAL" | "INSUFFICIENT_DATA";
export interface RiskDocument {
  status: RiskStatus;
  engine: string;
  domains: {
    water: { level: RiskStatus | null; origin: string; water_risk?: string; summary?: string; profile?: string | null; rules_status?: string; detail?: string };
    behavior: { level: null; origin: string; detail: string };
    data_quality: { level: RiskStatus | null; origin: string; detail: string };
    video: { level: null; origin: string; available: boolean; reliability: unknown; used_in_risk: false; detail: string };
  };
  evidence: { type: string; origin: string; parameter?: string; value?: number | null; unit?: string; level?: string; timestamp?: string; data_quality?: string }[];
  triggered_rules: { parameter?: string; level?: string; rule_id?: string | null; threshold?: number | null; direction?: string | null; confirmed?: boolean | null; provisional?: boolean; origin?: string }[];
  recommended_checks: string[];
  uncertainty: string[];
  cross_notes: string[];
  evaluated_at: string;
}

// ---- Structured Gemini explanation (§8.2/§8.3)
export interface ExplanationResponse {
  summary: string; water_quality_explanation: string; behavior_observations: string;
  risk_factors: string[]; supporting_evidence: string[]; recommended_checks: string[];
  missing_information: string[]; limitations: string[];
  provider: "groq" | "gemini"; model: string; tried: string[];
  generated_at: string; evidence_hash: string; cached: boolean; llm_generated: boolean;
  disclaimer: string; risk_status?: RiskStatus;
}

// ---- Persistent event history (§10F)
export interface HistoryRecord { ts: string; event: string; [k: string]: unknown }
// ---- API vision status + LLM behavior observation (replaces YOLO weights + RandomForest)
export interface VisionStatus {
  backend: "api" | "yolo";
  groq_configured: boolean; gemini_configured: boolean;
  groq_model: string | null; gemini_chain: string[]; fallback_order: string[];
  masks: boolean; note: string;
  groq_skipped?: boolean;
  providers?: Record<string, { calls: number; fails: number; last_status: number | null; last_error: string | null;
    last_retry_after_s: number | null; down_until: number | null; down_in_s: number | null }>;
}
export interface TrackSummary {
  track_id: number; observations: number; duration_sec?: string; mean_speed_px_sec?: string;
  median_speed_px_sec?: string; review_tracking?: string; review_reasons?: string; [k: string]: unknown;
}
export interface BehaviorObservation {
  provider: "groq" | "gemini"; model: string; observation: string;
  fallback_used: boolean; tried: string[]; generated_at: string;
  track_id: number; experimental: boolean; note: string;
}
// ---- LLM advice (Groq primary, Gemini fallback; computed by the backend, never in the browser)
export interface LlmStatus {
  groq_configured: boolean; gemini_configured: boolean;
  groq_model: string | null; gemini_model: string | null; fallback_order: string[];
}
export interface AdviceResponse {
  provider: "groq" | "gemini"; model: string; advice: string;
  fallback_used: boolean; tried: string[]; generated_at: string;
  waterRisk?: WaterRisk; overallStatus?: CombinedAssessment["overallStatus"];
}

// ---- Farmer finalization (A-H): alerts, predictions, behaviour windows, dashboard
export interface Khatra {
  score: number; level: "LOW" | "MEDIUM" | "HIGH";
  active: { rule: string; level: string; message: string; value?: number | null }[];
  weights: Record<string, number>; note: string;
}
export interface AlertItem {
  ts: string; t: number; id: string; rule: string; level: string; message: string;
  delivered: boolean; providers: string[]; statuses: string[]; phones_masked: (string | null)[];
  false_alarm?: boolean;
}
export interface AlertConfig {
  providers: string[]; textbee_configured: boolean; textbee_base_url?: string;
  phones_masked: string[]; phones_configured: number; dry_run: boolean;
  tank?: string; providers_configured?: Record<string, boolean>;
  provider_status?: Record<string, { ts?: string; status?: string; http_code?: number | null; latency_ms?: number | null }>;
  stale_alert_min: number; rules: Record<string, { label: string; cooldown_min: number; points: number }>;
}
export interface AlertsPayload { alerts: AlertItem[]; config: AlertConfig; khatra: Khatra; note: string }
export interface TestSmsResult {
  ok: boolean; delivered: boolean; reason?: string; dry_run: boolean;
  textbee_configured: boolean; phones_masked: (string | null)[]; phones_configured?: number;
  statuses: string[]; attempts: { provider: string; status: string; error?: string | null }[];
}
export interface ForecastPoint { t: number; iso: string; value: number; low: number; high: number }
export interface FieldForecast {
  field: string; status: "ok" | "insufficient_data"; unit: string; horizon_h: number;
  last?: { t: number; iso: string; value: number }; points: ForecastPoint[];
  backtest: { n: number; mae: number | null; mape: number | null; horizon_h: number };
  note: string; provisional: boolean; reason?: string;
  total_entries_analyzed?: number;
}
export interface DawnRisk {
  level: "LOW" | "MEDIUM" | "HIGH" | "INSUFFICIENT_DATA"; score: number | null;
  components?: Record<string, number>; evidence?: Record<string, number>;
  disclaimer?: string; provisional: boolean; reason?: string; ts?: string;
}
export interface Predictions {
  temperature: FieldForecast; turbidity: FieldForecast; dawn_risk: DawnRisk;
  anomalies: { provisional: boolean; fields: { field: string; status: string; flags: { kind: string; iso?: string; z?: number; value: number }[] }[] };
  note: string; provisional: boolean;
}
export interface BehaviorWindow {
  window_start: number; iso?: string; n_frames: number; n_obs: number;
  activity_norm: number | null; spread_norm: number | null; surface_occ: number | null;
  provisional?: boolean;
}
export interface BehaviorStatsData {
  provisional: boolean; experimental: boolean;
  latest: BehaviorWindow | null;
  series: { t: number; activity: number | null; spread: number | null; surface: number | null }[];
  baseline: { days: number; windows: number; hours_covered: number; ok: boolean };
  anomaly: { metric: string; z: number; sustained: boolean; windows: number; baseline_days: number } | null;
  metrics: Record<string, string>; disclaimer: string; note: string;
}
export interface DashboardData {
  khatra: Khatra;
  motor: { level: string; score: number | null; text: string; pump_rule: string; provisional: boolean; advisory_only: boolean };
  energy: { value: string; unit: string; note: string };
  sms: AlertConfig & { last_alert: AlertItem | null };
  alerts: AlertItem[];
  sensors: { latest: { t?: number; temperature?: number | null; turbidity?: number | null } | null; stats: { samples: number; span_hours: number; uptime_pct: number; stale_s: number | null; configured: boolean } };
  prediction: { dawn_risk: DawnRisk; behavior_anomaly: BehaviorStatsData["anomaly"] };
  ts: string; disclaimer: string;
}

// ---- Track II D1 / Track III BEH / Track IV F1 additive contracts
export type DoRiskLevel = "safe" | "watch" | "risk" | "critical" | null;
export interface DoPrediction {
  status: "ok" | "insufficient_data" | "disabled";
  do_mgl: number | null; band_low: number | null; band_high: number | null;
  percent_saturation: number | null; do_sat_mgl: number | null; s_factor: number | null;
  risk_level: DoRiskLevel; confidence: "low" | "medium" | "high";
  label_provisional: boolean;
  inputs: { temp_c: number | null; temp_age_min: number | null; turbidity_ntu: number | null;
    turbidity_age_min: number | null; ph: number | null; ph_age_hours: number | null };
  turbidity_unit: "raw_adc";
  behaviour_evidence: { hbs: number | null; state: string; sustained_min: number; source: string } | null;
  feed_evidence: { last_feed_age_h: number | null; s_feed: number; window_hours: [number, number]; advisory: string | null } | null;
  reason: string | null; generated_at: string; model_version: string;
}
export interface BehaviourSummary {
  state: "warming_up" | "calm" | "restless" | "hypoxia_suspect" | "no_data";
  hbs: number | null; sustained_min: number; view: "side" | "top" | null;
  window_start: string | null; window_end: string | null;
  metrics: Record<string, number | null>;
  z_scores: Record<string, number>;
  baseline: { days: number; required: number; windows: number; ok: boolean };
  threshold: number; label_provisional: boolean; model_version: string;
  reason: string | null; generated_at: string;
}
export interface FeedingEvent {
  id: string; fed_at: string; fed_t: number; farm_day: string; note: string | null;
  response: "aggressive" | "moderate" | "weak" | "none" | null;
  response_delta: number | null; response_updated_at: string | null;
  source: string; provisional: boolean; model_version: string;
}
export interface FeedingSummary {
  enabled: boolean; feedings: FeedingEvent[]; count: number; today: number;
  latest: FeedingEvent | null;
  dip: { last_feed_age_h: number | null; s_feed: number; window_hours: [number, number]; advisory: string | null };
  provisional: boolean; model_version: string;
}

export interface AuthStatus {
  enabled: boolean; providers_configured: Record<string, boolean>;
  otp_ttl_s: number; verified_count: number; verified_masked: (string | null)[]; note: string;
  /** Additive backend field (P1): "full" gates the app, "open" restores the pre-auth behaviour. */
  auth_mode?: "full" | "open";
}
export interface AuthUser {
  name?: string; phone?: string; tankId?: string; species?: string; system?: string;
}
export interface AuthLoginResult {
  ok: boolean; message?: string; phone_masked?: string; cooldown_s?: number; expires_in_s?: number; reason?: string;
}
export interface AuthVerifyResult {
  ok: boolean; user?: AuthUser; token?: string; csrf_token?: string; reason?: string;
}
export interface AuthMeResult {
  ok: boolean; user?: AuthUser; reason?: string;
}
