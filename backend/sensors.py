"""Read-only ThingSpeak poller for server-side rules (farmer finalization, B/C).

The browser already polls ThingSpeak for the live UI. Alert rules, predictions
and the weekly digest must keep working when no browser is open, so the backend
polls the same public channel read-only and stores regular samples.

Honest limits:
- field1/field2 are configured names, not calibrated units: temperature is °C
  as published by the channel, turbidity is the sensor's RAW ADC value (no NTU
  calibration is claimed).
- No key is ever logged. The read key travels only in the request URL.
- Storage: backend/data/sensors.jsonl (AQUA_BACKEND_DATA-aware), rotated at 50 MB.
"""
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

try:
    from backend.env import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass

MAX_FILE_BYTES = 50 * 1024 * 1024
HISTORY_MAX = 20000
_lock = threading.RLock()
_cache = None
_loaded = False
_thread = None
_stop = threading.Event()
_last_poll = {"t": None, "error": None, "new": 0}


def _data_dir():
    return Path(os.environ.get("AQUA_BACKEND_DATA",
                               Path(__file__).resolve().parents[1] / "backend" / "data"))


def _file():
    return _data_dir() / "sensors.jsonl"


def _env_int(name, default):
    try:
        v = int(os.environ.get(name, ""))
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


def config():
    """Channel/field configuration. `api_key` is never returned to clients."""
    return {
        "channel_id": os.environ.get("THINGSPEAK_CHANNEL_ID", "").strip(),
        "api_key": os.environ.get("THINGSPEAK_READ_KEY", "").strip(),
        "field_temperature": os.environ.get("THINGSPEAK_FIELD_TEMPERATURE", "1").strip() or "1",
        "field_turbidity": os.environ.get("THINGSPEAK_FIELD_TURBIDITY", "2").strip() or "2",
        "poll_s": _env_int("AQUA_SENSOR_POLL_S", 120),
    }


def configured():
    return bool(config()["channel_id"])


def _rotate(p, max_bytes=MAX_FILE_BYTES):
    try:
        if p.is_file() and p.stat().st_size > max_bytes:
            p.replace(p.with_suffix(p.suffix + ".1"))
    except OSError:
        pass


def _load():
    global _cache, _loaded
    with _lock:
        if _loaded:
            return _cache
        _cache = deque(maxlen=HISTORY_MAX)
        try:
            p = _file()
            if p.is_file():
                lines = p.read_text(encoding="utf-8").splitlines()[-HISTORY_MAX * 2:]
                for line in lines:
                    try:
                        rec = json.loads(line)
                        if isinstance(rec.get("t"), (int, float)):
                            _cache.append(rec)
                    except ValueError:
                        continue
        except OSError:
            pass
        _loaded = True
        return _cache


def _float_or_none(v):
    try:
        f = float(v)
        return f if f == f else None  # reject NaN
    except (TypeError, ValueError):
        return None


def _parse_ts(raw):
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return time.time()


def parse_feed(payload):
    """ThingSpeak feeds -> normalized samples (pure; used by tests)."""
    ch = config()
    ft, fb = f"field{ch['field_temperature']}", f"field{ch['field_turbidity']}"
    out = []
    for row in (payload or {}).get("feeds", []) or []:
        temp = _float_or_none(row.get(ft))
        turb = _float_or_none(row.get(fb))
        if temp is None and turb is None:
            continue
        try:
            entry = int(row.get("entry_id"))
        except (TypeError, ValueError):
            entry = None
        out.append({"t": _parse_ts(row.get("created_at")), "entry_id": entry,
                    "temperature": temp, "turbidity": turb})
    out.sort(key=lambda r: r["t"])
    return out


def fetch(timeout=15):
    """One read-only ThingSpeak request. Returns new samples (deduped by entry_id)."""
    ch = config()
    if not ch["channel_id"]:
        return []
    # Request up to 8000 results to cover all entries from ThingSpeak cloud
    q = {"results": 8000}
    if ch["api_key"]:
        q["api_key"] = ch["api_key"]
    url = f"https://api.thingspeak.com/channels/{urllib.parse.quote(ch['channel_id'])}/feeds.json?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, headers={"User-Agent": "AquaCultureAI/1.0 (read-only)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = json.loads(r.read().decode("utf-8", "replace"))
    samples = parse_feed(payload)
    cache = _load()
    existing_ids = {rec.get("entry_id") for rec in cache if rec.get("entry_id") is not None}
    fresh = [s for s in samples if s.get("entry_id") not in existing_ids]
    if fresh:
        p = _file()
        p.parent.mkdir(parents=True, exist_ok=True)
        _rotate(p)
        with _lock:
            # Combine all records and sort chronologically
            all_records = list(cache) + fresh
            all_records.sort(key=lambda s: (s.get("t") or 0, s.get("entry_id") or 0))
            # Rewrite sensors.jsonl with clean sorted deduplicated history
            with p.open("w", encoding="utf-8") as f:
                for s in all_records[-HISTORY_MAX:]:
                    f.write(json.dumps(s, ensure_ascii=False) + "\n")
            _cache.clear()
            _cache.extend(all_records[-HISTORY_MAX:])
    _last_poll.update(t=time.time(), error=None, new=len(fresh))
    return fresh


def poll_once():
    try:
        return fetch()
    except Exception as e:  # network/JSON failure must never break the scheduler
        _last_poll.update(t=time.time(), error=f"{type(e).__name__}: {str(e)[:120]}", new=0)
        return []


def _loop():
    while not _stop.is_set():
        if configured():
            poll_once()
        _stop.wait(config()["poll_s"])


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="aqua-sensors", daemon=True)
    _thread.start()


def stop():
    _stop.set()


def recent(minutes=1440):
    cutoff = time.time() - minutes * 60
    return [r for r in list(_load()) if (r.get("t") or 0) >= cutoff]


def latest():
    rows = list(_load())
    return rows[-1] if rows else None


def series(field, minutes=1440):
    out = []
    rows = recent(minutes) if minutes is not None else list(_load())
    for r in rows:
        v = r.get(field)
        if isinstance(v, (int, float)):
            # Filter non-physical zeros (e.g. uninitialized sensor probe)
            if v > 0:
                out.append((float(r["t"]), float(v)))
    out.sort(key=lambda x: x[0])
    return out


def stats(hours=24):
    rows = recent(hours * 60)
    now = time.time()
    span = (now - rows[0]["t"]) / 3600 if rows else 0.0
    expected = max(1, int(hours * 60 / max(1, config()["poll_s"])))
    last = latest()
    last_t = last.get("t") if last else None
    return {
        "configured": configured(),
        "samples": len(rows),
        "total_samples": len(_load()),
        "span_hours": round(span, 2),
        "uptime_pct": round(min(100.0, 100.0 * len(rows) / expected), 1),
        "stale_s": round(now - last_t) if last_t else None,
        "last_entry": last,
        "last_error": _last_poll.get("error"),
        "poll_s": config()["poll_s"],
    }


def status():
    ch = config()
    return {"configured": bool(ch["channel_id"]), "channel_id": ch["channel_id"] or None,
            "poll_s": ch["poll_s"], "fields": {"temperature": ch["field_temperature"],
            "turbidity": ch["field_turbidity"]}, **{k: v for k, v in stats().items() if k != "configured"},
            "note": "Read-only ThingSpeak mirror; turbidity is raw ADC, not NTU."}
