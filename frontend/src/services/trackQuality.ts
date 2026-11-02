// CONF-C track-quality proxy. Florence-2 `<OD>` emits a constant box score
// (R-B4); this module replaces the displayed constant with a motion-based q.
// Constants are fixed by the CONF-C spec: q = .35*persistence + .30*stability
// + .20*shape_prior + .15*velocity_ok.
export type QualityBand = "high" | "medium" | "low";
export type Box = [number, number, number, number];

/** VITE_TRACK_CONF=0 keeps the legacy constant Florence score; default 1. */
export function trackConfEnabled(value: string | undefined | null): boolean {
  return value !== "0";
}

export interface TrackSample {
  id: number;
  observations: number;
  box?: Box;
  mean_speed_px_sec?: number | null;
  confirmed?: boolean;
  static?: boolean;
}

export interface TrackQuality {
  q: number;
  band: QualityBand;
  persistence: number;
  stability: number;
  shapePrior: number;
  velocityOk: number;
}

export interface FrameQuality {
  score: number;
  band: QualityBand;
  tracks: number;
}

export interface TrackerResult {
  byTrack: Map<number, TrackQuality>;
  frame: FrameQuality | null;
}

interface ShapeStats {
  aspectMean: number;
  aspectStd: number;
  areaMean: number;
  areaStd: number;
}

interface Entry {
  boxes: Box[];
  ious: number[];
  shapeContributed: boolean;
  speedContributed: boolean;
}

const clamp01 = (value: number) => Math.max(0, Math.min(1, value));
const mean = (values: number[]) => values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;

export function persistenceScore(ageCycles: number): number {
  return clamp01(Math.max(0, ageCycles) / 3);
}

export function iou(a: Box, b: Box): number {
  const x1 = Math.max(a[0], b[0]);
  const y1 = Math.max(a[1], b[1]);
  const x2 = Math.min(a[2], b[2]);
  const y2 = Math.min(a[3], b[3]);
  const intersection = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
  const areaA = Math.max(0, a[2] - a[0]) * Math.max(0, a[3] - a[1]);
  const areaB = Math.max(0, b[2] - b[0]) * Math.max(0, b[3] - b[1]);
  const union = areaA + areaB - intersection;
  return union > 0 ? clamp01(intersection / union) : 0;
}

export function stabilityScore(ious: number[]): number {
  // mean IoU of the predicted-vs-observed box over the last 3 cycles.
  return clamp01(mean(ious.slice(-3)));
}

export function shapeStats(samples: { aspect: number; area: number }[]): ShapeStats | null {
  // Self-learned session stats from tracks that survived >= 10 cycles; never sent to the backend.
  if (samples.length < 2) return null;
  const aspects = samples.map((s) => s.aspect);
  const areas = samples.map((s) => s.area);
  const aspectMean = mean(aspects);
  const areaMean = mean(areas);
  const variance = (values: number[], avg: number) => mean(values.map((v) => (v - avg) ** 2));
  return {
    aspectMean,
    aspectStd: Math.max(1e-6, Math.sqrt(variance(aspects, aspectMean))),
    areaMean,
    areaStd: Math.max(1e-6, Math.sqrt(variance(areas, areaMean))),
  };
}

export function shapePrior(aspect: number, area: number, stats: ShapeStats | null): number {
  // Neutral 0.5 until the session has enough long-lived shape samples.
  if (!stats) return 0.5;
  const za = (aspect - stats.aspectMean) / stats.aspectStd;
  const zA = (area - stats.areaMean) / stats.areaStd;
  return clamp01(Math.exp(-0.5 * (za * za + zA * zA)));
}

export function velocityScore(speed: number | null | undefined, vRef: number | null): number {
  // vRef = 1.5 * session p95 of long-lived speeds; no reference yet => neutral-optimistic.
  if (vRef === null || vRef <= 0) return 1;
  if (speed === null || speed === undefined || !Number.isFinite(speed)) return 0.5;
  if (speed <= vRef) return 1;
  return clamp01(1 - (speed - vRef) / (2 * vRef));
}

export function compositeQuality(parts: {
  persistence: number;
  stability: number;
  shapePrior: number;
  velocityOk: number;
}): number {
  return clamp01(
    0.35 * clamp01(parts.persistence) +
    0.3 * clamp01(parts.stability) +
    0.2 * clamp01(parts.shapePrior) +
    0.15 * clamp01(parts.velocityOk)
  );
}

export function qualityBand(q: number): QualityBand {
  // CONF-C bands: high >= 0.75, medium 0.50-0.74, low < 0.50.
  return q >= 0.75 ? "high" : q >= 0.5 ? "medium" : "low";
}

export function frameQuality(qualities: TrackQuality[]): FrameQuality | null {
  if (qualities.length === 0) return null;
  const score = mean(qualities.map((quality) => quality.q));
  return { score, band: qualityBand(score), tracks: qualities.length };
}

export function formatQualityLabel(quality: TrackQuality | null | undefined, legacyConfidence: number, enabled = true): string {
  if (!enabled) return legacyConfidence.toFixed(2);
  return quality ? `${Math.round(quality.q * 100)}%·${quality.band}` : "untracked";
}

export function percentile(values: number[], p: number): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil(p * sorted.length) - 1));
  return sorted[index];
}

function boxShape(box: Box) {
  const width = Math.max(1e-6, box[2] - box[0]);
  const height = Math.max(1e-6, box[3] - box[1]);
  return { aspect: width / height, area: width * height };
}

function predictedBox(boxes: Box[]): Box {
  const last = boxes[boxes.length - 1];
  if (!last) return [0, 0, 0, 0];
  const previous = boxes[boxes.length - 2];
  if (!previous) return last;
  return [last[0] + (last[0] - previous[0]), last[1] + (last[1] - previous[1]),
    last[2] + (last[2] - previous[2]), last[3] + (last[3] - previous[3])];
}

export function createTrackQuality() {
  const history = new Map<number, Entry>();
  const shapes: { aspect: number; area: number }[] = [];
  const longSpeeds: number[] = [];
  let latest: Map<number, TrackQuality> = new Map();

  const update = (tracks: TrackSample[]): TrackerResult => {
    const confirmed = tracks.filter((track) => track.confirmed !== false && track.static !== true && track.box);
    const currentIds = new Set(confirmed.map((track) => track.id));
    const byTrack = new Map<number, TrackQuality>();

    for (const track of confirmed) {
      const box = track.box!;
      const entry = history.get(track.id) ?? { boxes: [], ious: [], shapeContributed: false, speedContributed: false };
      history.set(track.id, entry);

      if (entry.boxes.length > 0) {
        entry.ious.push(iou(predictedBox(entry.boxes), box));
        entry.ious = entry.ious.slice(-3);
      }
      entry.boxes = [...entry.boxes, box].slice(-3);

      const shape = boxShape(box);
      if (track.observations >= 10 && !entry.shapeContributed) {
        shapes.push(shape);
        entry.shapeContributed = true;
      }
      if (track.observations >= 10 && track.mean_speed_px_sec !== null && track.mean_speed_px_sec !== undefined && !entry.speedContributed) {
        longSpeeds.push(track.mean_speed_px_sec);
        entry.speedContributed = true;
      }

      const stats = shapeStats(shapes);
      const speedRef = percentile(longSpeeds, 0.95);
      const parts = {
        persistence: persistenceScore(track.observations),
        stability: stabilityScore(entry.ious),
        shapePrior: shapePrior(shape.aspect, shape.area, stats),
        velocityOk: velocityScore(track.mean_speed_px_sec, speedRef === null ? null : speedRef * 1.5),
      };
      const q = compositeQuality(parts);
      byTrack.set(track.id, { q, band: qualityBand(q), ...parts });
    }

    for (const id of history.keys()) if (!currentIds.has(id)) history.delete(id);
    latest = byTrack;
    return { byTrack, frame: frameQuality([...byTrack.values()]) };
  };

  return {
    update,
    get: (id: number) => latest.get(id),
    latest: () => latest,
  };
}

export type TrackQualityTracker = ReturnType<typeof createTrackQuality>;
