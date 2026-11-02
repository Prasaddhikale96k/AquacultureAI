"""Stateful live-frame tracking for the ~1 fps live camera loop.

The frame endpoints are stateless per request, but tracking needs memory:
this module keeps short per-session track buffers keyed by a client-generated
session id. Greedy centroid matching (no invented identities: ids are
session-local and reported as such), gap-aware speeds, and camera-motion gating.

Honest limits, always surfaced:
- 1 fps sampling is coarse: speeds are approximate, fast motion aliases, and
  identities fragment on missed detections. Track ids must never be read as
  stable fish identities across long gaps.
- Camera shift is estimated by phase correlation on downscaled frames. Measured
  on the static test video (test_videos/tilapia_clear.mp4, 1 s sampling):
  static-camera shift reaches ~0.08 of the frame diagonal with response often
  < 0.3 (fish motion contaminates the global estimate). Compensation at this
  sampling rate is therefore unreliable: camera state is {still, moving,
  unknown}, and speeds are marked approximate whenever the state is not still.
- Stationary classification uses an explicitly labeled heuristic threshold
  (STILL_PX_SEC), reported as experimental, never as validated behaviour.
"""
import math
import os
import threading
import time
from collections import deque

import cv2
import numpy as np

SESSION_TTL_SEC = 60        # idle sessions expire; expiry records one history summary
GATE_FRAC = 0.12            # match gate: centroid distance as fraction of frame diagonal
MAX_MISS = 3                # drop a track after this many consecutive misses
SPEED_DT_MIN = 0.2          # ignore intervals shorter than this (same-frame duplicates)
SPEED_DT_MAX = 2.5          # never compute speed across longer gaps as if continuous
STILL_PX_SEC = 10.0         # heuristic stationary threshold (experimental, reported as such)
CAM_RESP_MIN = 0.3          # phase-correlation response below this -> camera state unknown
CAM_MOVE_FRAC = 0.15        # shift above this (with decent response) -> camera moving
MOTION_GRID = (8, 6)        # per-cell motion support grid over the small gray frame
MOTION_CELLS_N = 5          # support window: detection needs motion in >=3 of last 5 frames
MOTION_CELLS_NEED = 3
MOTION_DIFF_MIN = 25 / 255  # mean |frame diff| inside the cell to count as motion (measured: 1.7 ms/frame)
CONFIRM_WINDOW = 5          # a track is confirmed when it matched in >=3 of its last 5 frames
CONFIRM_MIN_HITS = 3


def _env_int(name, default):
    raw = os.environ.get(name)
    try:
        v = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return v if v >= 1 else default


def confirm_window():
    """AQUA_CONFIRM_WINDOW: frames considered for confirmation (default 5, A3: 3)."""
    return _env_int("AQUA_CONFIRM_WINDOW", CONFIRM_WINDOW)


def confirm_min_hits():
    """AQUA_CONFIRM_HITS: matches needed inside the window (default 3, A3: 2)."""
    return min(_env_int("AQUA_CONFIRM_HITS", CONFIRM_MIN_HITS), confirm_window())


def motion_gate_on():
    """AQUA_MOTION_GATE=0 disables the gate instantly (rollback, no code edit)."""
    raw = os.environ.get("AQUA_MOTION_GATE")
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def static_filter_on():
    """G2: AQUA_STATIC_FILTER=0 disables the static-track fade/count exclusion."""
    raw = os.environ.get("AQUA_STATIC_FILTER")
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def static_px_sec():
    """G2: speed below this (px/s at 640 px width) marks a track static."""
    try:
        v = float(os.environ.get("AQUA_STATIC_PX", "20"))
        return v if v > 0 else 20.0
    except (TypeError, ValueError):
        return 20.0


def _motion_support(past_grays, current, centroid):
    """Frames (of up to the last 5) in which the detection's grid cell shows
    motion vs the current frame. <3 frames of history: pass (never block)."""
    if len(past_grays) < 3:
        return MOTION_CELLS_NEED  # too little history to judge: pass, never block startup
    gx = min(MOTION_GRID[0] - 1, max(0, int(centroid[0] * MOTION_GRID[0])))
    gy = min(MOTION_GRID[1] - 1, max(0, int(centroid[1] * MOTION_GRID[1])))
    h, w = current.shape[:2]
    x1, x2 = gx * w // MOTION_GRID[0], (gx + 1) * w // MOTION_GRID[0]
    y1, y2 = gy * h // MOTION_GRID[1], (gy + 1) * h // MOTION_GRID[1]
    cur = current.astype(np.float32)[y1:y2, x1:x2]
    if cur.size == 0:
        return 0
    n = 0
    for g in list(past_grays)[-MOTION_CELLS_N:]:
        if g.shape != current.shape:
            continue
        cell = np.abs(cur - g.astype(np.float32)[y1:y2, x1:x2])
        if cell.size and cell.mean() / 255.0 >= MOTION_DIFF_MIN:
            n += 1
    return n

_lock = threading.RLock()
_sessions = {}
_next_session_seq = [0]


def _new_id(session):
    session["next_id"] += 1
    return session["next_id"]


def _get(session_id):
    with _lock:
        s = _sessions.get(session_id)
        if s is None:
            s = {"tracks": {}, "next_id": 0, "prev_gray": None, "prev_t": None,
                 "frames": 0, "first_t": None, "counts": [], "last_seen": None,
                 "grays": deque(maxlen=MOTION_CELLS_N)}
            _sessions[session_id] = s
        return s


def _small_gray(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    scale = 320 / max(1, g.shape[1])
    return cv2.resize(g, (320, max(1, round(g.shape[0] * scale))), interpolation=cv2.INTER_AREA)


def _camera_state(prev_gray, gray):
    """(state, shift_frac, response) measured from two downscaled gray frames."""
    if prev_gray is None or prev_gray.shape != gray.shape:
        return "unknown", 0.0, 0.0
    try:
        from school_movement_metrics import camera_shift
        dx, dy, resp = camera_shift(prev_gray.astype(np.float32), gray.astype(np.float32))
    except Exception:
        return "unknown", 0.0, 0.0
    diag = float(np.hypot(*gray.shape))
    shift = float(np.hypot(dx, dy)) / diag if diag else 0.0
    if not np.isfinite(shift) or not np.isfinite(resp):
        return "unknown", 0.0, 0.0
    if resp < CAM_RESP_MIN:
        return "unknown", round(shift, 4), round(float(resp), 3)
    if shift > CAM_MOVE_FRAC:
        return "moving", round(shift, 4), round(float(resp), 3)
    return "still", round(shift, 4), round(float(resp), 3)


def _centroid(box):
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def update(session_id, img, detections, now=None):
    """Fold one frame's accepted detections into the session. Returns tracking + movement dicts."""
    now = time.time() if now is None else float(now)
    h, w = img.shape[:2]
    diag_px = float(np.hypot(w, h))
    gray = _small_gray(img)
    with _lock:
        s = _get(session_id)
        s["last_seen"] = now  # caller clock (production: wall time), so TTL/sweep stay consistent
        if s["first_t"] is None:
            s["first_t"] = now
        s["frames"] += 1
        s["counts"].append(len(detections))
        cam_state, shift, resp = _camera_state(s["prev_gray"], gray)
        s["prev_gray"] = gray

        cents_all = [_centroid(d["box"]) for d in detections]
        # T4 motion gate: static decor/background detections (no motion support
        # in >=3 of the last 5 frames) never enter tracking. Bypassed only via
        # AQUA_MOTION_GATE=0; young sessions (<3 frames history) always pass.
        grays = s.setdefault("grays", deque(maxlen=MOTION_CELLS_N))
        motion_gated = 0
        if motion_gate_on() and detections:
            kept = []
            for d, c in zip(detections, cents_all):
                if _motion_support(grays, gray, c) >= MOTION_CELLS_NEED:
                    kept.append(d)
                else:
                    motion_gated += 1
            detections = kept
            cents = [_centroid(d["box"]) for d in detections]
        else:
            cents = cents_all
        grays.append(gray)
        matched_det = set()
        matches = {}  # det_idx -> track_id
        # greedy nearest-centroid matching, highest confidence first
        order = sorted(range(len(detections)), key=lambda i: -float(detections[i].get("confidence", 0)))
        for i in order:
            best, bi = GATE_FRAC, None
            for tid, tr in s["tracks"].items():
                if tid in matches.values():
                    continue
                dx = cents[i][0] - tr["centroid"][0]
                dy = cents[i][1] - tr["centroid"][1]
                dist = math.hypot(dx, dy)
                if dist < best:
                    best, bi = dist, tid
            if bi is not None:
                matches[i] = bi
                matched_det.add(i)
        gaps_skipped = 0
        for i, c in enumerate(cents):
            if i in matches:
                tid = matches[i]
                tr = s["tracks"][tid]
                dt = now - tr["last_t"]
                if SPEED_DT_MIN < dt <= SPEED_DT_MAX:
                    dist_px = math.hypot(c[0] - tr["centroid"][0], c[1] - tr["centroid"][1]) * diag_px
                    tr["speeds"].append(dist_px / dt)
                else:
                    gaps_skipped += 1  # too short or too long: no speed invented across it
                tr["hits"] = (tr["hits"] + [1])[-confirm_window():]
                tr.update(centroid=c, last_t=now, misses=0,
                          obs=tr["obs"] + 1, conf=float(detections[i].get("confidence", 0)),
                          box=[float(v) for v in detections[i]["box"]])
            else:
                tid = _new_id(s)
                s["tracks"][tid] = {"id": tid, "centroid": c, "first_t": now, "last_t": now,
                                    "misses": 0, "obs": 1, "speeds": [], "hits": [1],
                                    "box": [float(v) for v in detections[i]["box"]],
                                    "conf": float(detections[i].get("confidence", 0))}
        for tid in [t for t in s["tracks"] if t not in matches.values()]:
            s["tracks"][tid]["misses"] += 1
            s["tracks"][tid]["hits"] = (s["tracks"][tid]["hits"] + [0])[-confirm_window():]
        for tid in [t for t, tr in s["tracks"].items() if tr["misses"] > MAX_MISS]:
            del s["tracks"][tid]

        tracks = []
        all_speeds = []
        static_thr = static_px_sec() * (w / 640.0)
        for tr in sorted(s["tracks"].values(), key=lambda t: t["id"]):
            mean_sp = (sum(tr["speeds"]) / len(tr["speeds"])) if tr["speeds"] else None
            if mean_sp is not None:
                all_speeds.append(mean_sp)
            static = bool(static_filter_on() and mean_sp is not None
                          and len(tr["speeds"]) >= 3 and mean_sp < static_thr)
            
            # Fish Behaviour Classification (§BEH: real-time camera proxy)
            b = tr["box"]
            cy = (b[1] + b[3]) / 2.0
            if cy < 0.20 or b[1] < 0.15:
                zone = "surface"
                zone_label = "Surface (Top 15%)"
            elif cy > 0.75:
                zone = "bottom"
                zone_label = "Bottom Layer"
            else:
                zone = "midwater"
                zone_label = "Midwater Column"

            if mean_sp is None:
                beh_state = "tracking"
                beh_label = "Acquiring..."
                beh_tone = "mute"
            elif mean_sp < STILL_PX_SEC or static:
                if zone == "surface":
                    beh_state = "surface_gasping"
                    beh_label = "Surface Gasping (Low DO?)"
                    beh_tone = "bad"
                elif zone == "bottom":
                    beh_state = "resting_bottom"
                    beh_label = "Bottom Resting"
                    beh_tone = "info"
                else:
                    beh_state = "resting"
                    beh_label = "Resting / Stationary"
                    beh_tone = "info"
            elif mean_sp > 65.0:
                beh_state = "erratic"
                beh_label = "Fast / Erratic Swimming"
                beh_tone = "warn"
            else:
                if zone == "surface":
                    beh_state = "surface_swimming"
                    beh_label = "Surface Swimming"
                    beh_tone = "warn"
                else:
                    beh_state = "normal_swimming"
                    beh_label = "Normal Swimming"
                    beh_tone = "ok"

            tracks.append({"id": tr["id"], "observations": tr["obs"],
                           "duration_sec": round(now - tr["first_t"], 2),
                           "mean_speed_px_sec": round(mean_sp, 1) if mean_sp is not None else None,
                           "last_seen_sec_ago": round(now - tr["last_t"], 2),
                           "confidence": round(tr["conf"], 3),
                           "confirmed": sum(tr["hits"]) >= confirm_min_hits(),
                           "static": static,
                           "box": [round(float(v), 4) for v in tr["box"]],
                           "behavior": {
                               "state": beh_state,
                               "label": beh_label,
                               "zone": zone,
                               "zone_label": zone_label,
                               "tone": beh_tone,
                           }})
        # Cap live tracks to max_fishes (user tank has at most 2 fish)
        max_f = _env_int("AQUA_MAX_FISHES", 2)
        if len(tracks) > max_f:
            tracks.sort(key=lambda t: (not t["static"], t["confirmed"], t["observations"], t.get("confidence", 0)), reverse=True)
            tracks = tracks[:max_f]
            tracks.sort(key=lambda t: t["id"])
        still_intervals = 0
        valid_intervals = 0
        for tr in s["tracks"].values():
            for sp in tr["speeds"]:
                valid_intervals += 1
                if sp < STILL_PX_SEC:
                    still_intervals += 1
        static_n = sum(1 for t in tracks if t["static"])
        confirmed_active = [t for t in tracks if not t["static"] and t["confirmed"]]

        # Tank / School Behaviour State Assessment
        surface_fish = [t for t in confirmed_active if t["behavior"]["zone"] == "surface"]
        surface_frac = len(surface_fish) / len(confirmed_active) if confirmed_active else 0.0
        
        schooling_state = "Single Fish"
        if len(confirmed_active) == 2:
            b1 = confirmed_active[0]["box"]
            b2 = confirmed_active[1]["box"]
            dist = math.hypot(((b1[0] + b1[2]) / 2) - ((b2[0] + b2[2]) / 2),
                              ((b1[1] + b1[3]) / 2) - ((b2[1] + b2[3]) / 2))
            schooling_state = f"Paired Swimming ({round(dist * 100)}% dist)" if dist < 0.35 else "Dispersed Swimming"

        if not confirmed_active:
            if tracks:
                overall_state = "detecting"
                overall_label = "Detecting Fish Movement"
                status_tone = "info"
                detail = "Establishing fish track and velocity baseline"
            else:
                overall_state = "no_fish"
                overall_label = "No Fish Tracked"
                status_tone = "mute"
                detail = "Camera running, waiting for fish in frame"
        elif any(t["behavior"]["state"] == "surface_gasping" for t in confirmed_active):
            overall_state = "surface_gasping"
            overall_label = "Surface Gasping (Low DO Alert)"
            status_tone = "bad"
            detail = "Fish lingering at surface with reduced movement — inspect aeration and oxygen levels immediately!"
        elif any(t["behavior"]["state"] == "erratic" for t in confirmed_active):
            overall_state = "erratic_swimming"
            overall_label = "Erratic / Fast Swimming"
            status_tone = "warn"
            detail = "Elevated speed or agitated darting detected in tank"
        elif any(t["behavior"]["state"] == "surface_swimming" for t in confirmed_active):
            overall_state = "surface_activity"
            overall_label = "Surface Activity"
            status_tone = "warn"
            detail = "Fish active in the top water layer (feeding search or early hypoxia)"
        elif all("resting" in t["behavior"]["state"] for t in confirmed_active):
            overall_state = "calm_resting"
            overall_label = "Calm / Resting"
            status_tone = "ok"
            detail = "Fish holding station peacefully with low movement"
        else:
            overall_state = "normal_swimming"
            overall_label = "Normal Active Swimming"
            status_tone = "ok"
            detail = f"Healthy cruising across midwater column ({schooling_state})"

        mean_speed = round(sum(all_speeds) / len(all_speeds), 1) if all_speeds else None
        if mean_speed is None:
            activity_level = "Acquiring..."
        elif mean_speed < STILL_PX_SEC:
            activity_level = "Low / Resting"
        elif mean_speed < 45.0:
            activity_level = "Moderate / Cruising"
        elif mean_speed < 70.0:
            activity_level = "Active"
        else:
            activity_level = "High / Rapid"

        behavior = {
            "overall_state": overall_state,
            "overall_label": overall_label,
            "status_tone": status_tone,
            "detail": detail,
            "surface_proxy_pct": round(surface_frac * 100, 1),
            "activity_level": activity_level,
            "schooling_state": schooling_state,
            "active_fish_count": len(confirmed_active),
        }

        movement = {
            "track_count": len(tracks),
            "active_track_count": len(tracks) - static_n,
            "static_tracks": static_n,
            "static_threshold_px_sec": round(static_thr, 1),
            "valid_speed_intervals": valid_intervals,
            "gaps_skipped": gaps_skipped,
            "mean_speed_px_sec": mean_speed,
            "stationary_frac": round(still_intervals / valid_intervals, 3) if valid_intervals else None,
            "still_threshold_px_sec": STILL_PX_SEC,
            "camera": {"state": cam_state, "shift_frac": shift, "response": resp},
            "speeds_approximate": cam_state != "still",
            "motion_gated": motion_gated,
            "motion_gate": motion_gate_on(),
            "static_filter": static_filter_on(),
            "experimental": True,
            "note": ("Speeds from ~1 fps centroid matching; approximate, session-local identities. "
                     "Stationary threshold is a heuristic, not a validated behaviour cutoff. "
                     "Static tracks are faded and excluded from the fish count."),
        }
        return {"tracks": tracks, "movement": movement, "behavior": behavior,
                "session": {"id": session_id, "frames_processed": s["frames"],
                            "session_sec": round(now - s["first_t"], 1)}}


def status(now=None):
    """Allow-listed live-engine state for diagnostics (no frames, no images)."""
    now = time.time() if now is None else float(now)
    with _lock:
        sessions = list(_sessions.values())
    active = [s for s in sessions
              if now - (s.get("last_seen") if s.get("last_seen") is not None else now) <= SESSION_TTL_SEC]
    last = max((s.get("last_seen") for s in sessions if s.get("last_seen") is not None), default=None)
    return {"active_sessions": len(active), "known_sessions": len(sessions),
            "warm": bool(active), "last_activity_age_s": round(now - last) if last is not None else None}


def sweep(now=None):
    """Expire idle sessions. Returns one genuine summary per expired session for history."""
    now = time.time() if now is None else float(now)
    expired = []
    with _lock:
        for sid in [k for k, s in _sessions.items()
                    if now - (s.get("last_seen") if s.get("last_seen") is not None else now) > SESSION_TTL_SEC]:
            s = _sessions.pop(sid)
            if s["frames"] >= 2:
                counts = s["counts"]
                expired.append({"session_id": sid, "frames": s["frames"],
                                "duration_sec": round(now - (s["first_t"] or now), 1),
                                "mean_detections": round(sum(counts) / len(counts), 2),
                                "tracks_seen": s["next_id"]})
    return expired
