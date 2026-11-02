import type { RecentAnalysis } from "../types";

/** DEMO ONLY: illustrative rows shown (and labelled) when no history backend exists. Not real analyses. */
export const DEMO_RECENT: RecentAnalysis[] = [
  { id: "demo-1", filename: "sample_tank_clip_A.mp4", at: "Sample entry", status: "completed", source: "demo" },
  { id: "demo-2", filename: "sample_tank_clip_B.mp4", at: "Sample entry", status: "needs_review", source: "demo" },
  { id: "demo-3", filename: "sample_tank_clip_C.mp4", at: "Sample entry", status: "failed", source: "demo" },
];
