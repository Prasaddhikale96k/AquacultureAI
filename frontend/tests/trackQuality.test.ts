import test from "node:test";
import assert from "node:assert/strict";
import {
  compositeQuality,
  createTrackQuality,
  formatQualityLabel,
  frameQuality,
  iou,
  percentile,
  persistenceScore,
  qualityBand,
  shapePrior,
  shapeStats,
  stabilityScore,
  trackConfEnabled,
  velocityScore,
  type TrackQuality,
} from "../src/services/trackQuality.ts";

const close = (a: number, b: number, epsilon = 1e-9) => assert.ok(Math.abs(a - b) < epsilon, `${a} != ${b}`);

const quality = (q: number): TrackQuality => ({
  q,
  band: qualityBand(q),
  persistence: q,
  stability: q,
  shapePrior: q,
  velocityOk: q,
});

test("persistence is age/3, capped at 1", () => {
  close(persistenceScore(1), 1 / 3);
  close(persistenceScore(3), 1);
  close(persistenceScore(5), 1);
});

test("IoU and stability use the last three cycles", () => {
  close(iou([0, 0, 1, 1], [0, 0, 1, 1]), 1);
  close(iou([0, 0, 1, 1], [0.5, 0, 1.5, 1]), 1 / 3);
  close(stabilityScore([0.2, 0.5, 0.8, 1]), 0.7666666666666667);
});

test("shape prior peaks at the learned mean and falls away from it", () => {
  const stats = shapeStats([{ aspect: 2, area: 0.1 }, { aspect: 4, area: 0.2 }]);
  assert.ok(stats);
  close(shapePrior(3, 0.15, stats), 1);
  assert.ok(shapePrior(6, 0.3, stats) < 0.6);
  close(shapePrior(3, 0.15, null), 0.5);
});

test("velocity decays only beyond the session reference", () => {
  close(velocityScore(100, 100), 1);
  close(velocityScore(150, 100), 0.75);
  close(velocityScore(300, 100), 0);
  close(velocityScore(null, 100), 0.5);
  close(velocityScore(100, null), 1);
});

test("composite weights and band boundaries match CONF-C", () => {
  close(compositeQuality({ persistence: 1, stability: 1, shapePrior: 1, velocityOk: 1 }), 1);
  close(compositeQuality({ persistence: 1 / 3, stability: 0.5, shapePrior: 0.5, velocityOk: 0.75 }), 0.4791666666666667);
  assert.equal(qualityBand(0.75), "high");
  assert.equal(qualityBand(0.74), "medium");
  assert.equal(qualityBand(0.5), "medium");
  assert.equal(qualityBand(0.49), "low");
});

test("frame score averages tracks and is null when empty", () => {
  const frame = frameQuality([quality(0.8), quality(0.4)]);
  assert.ok(frame);
  close(frame.score, 0.6);
  assert.equal(frame.band, "medium");
  assert.equal(frame.tracks, 2);
  assert.equal(frameQuality([]), null);
});

test("labels show percent and band, or legacy 0.50 on rollback", () => {
  assert.equal(trackConfEnabled(undefined), true);
  assert.equal(trackConfEnabled("1"), true);
  assert.equal(trackConfEnabled("0"), false);
  assert.equal(formatQualityLabel(quality(0.823), 0.5), "82%·high");
  assert.equal(formatQualityLabel(quality(0.49), 0.5), "49%·low");
  assert.equal(formatQualityLabel(quality(0.8), 0.5, trackConfEnabled("0")), "0.50");
  assert.equal(formatQualityLabel(undefined, 0.5), "untracked");
});

test("tracker builds q across cycles and clears missing tracks", () => {
  const tracker = createTrackQuality();
  let result = tracker.update([{ id: 1, observations: 1, box: [0.1, 0.1, 0.3, 0.3], mean_speed_px_sec: 10, confirmed: true }]);
  assert.equal(result.frame?.tracks, 1);
  const first = result.byTrack.get(1)?.q ?? 0;
  result = tracker.update([{ id: 1, observations: 3, box: [0.12, 0.1, 0.32, 0.3], mean_speed_px_sec: 10, confirmed: true }]);
  const third = result.byTrack.get(1)?.q ?? 0;
  assert.ok(third > first);
  result = tracker.update([]);
  assert.equal(result.frame, null);
  assert.equal(tracker.latest().size, 0);
});

test("p95 picks the nearest-rank value", () => {
  close(percentile([1, 2, 3, 4, 5], 0.95) ?? 0, 5);
  close(percentile([5, 1, 3], 0.5) ?? 0, 3);
  assert.equal(percentile([], 0.95), null);
});
