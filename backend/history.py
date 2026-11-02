"""Persistent event history: append-only JSON lines (existing persistence approach).

Records genuine analysis events only: video analyses, saved water readings,
generated explanations. Each record carries a timestamp, engine/version info
and the outcome status. Never stores API keys, raw uploads or secrets.

Storage: backend/data/history.jsonl (AQUA_BACKEND_DATA-aware).
"""
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

_lock = threading.RLock()
MAX_LIMIT = 200


def _file():
    base = Path(os.environ.get("AQUA_BACKEND_DATA",
                               Path(__file__).resolve().parents[1] / "backend" / "data"))
    return base / "history.jsonl"


def record(event, **fields):
    """Append one event. Never raises (history must not break the request)."""
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "event": event}
    for k, v in fields.items():
        if k.lower() in ("api_key", "apikey", "secret", "key"):
            continue
        try:
            json.dumps(v)
            rec[k] = v
        except (TypeError, ValueError):
            rec[k] = str(v)[:500]
    try:
        with _lock:
            p = _file()
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read_all():
    out, skipped = [], 0
    try:
        with _lock:
            p = _file()
            if not p.is_file():
                return [], 0
            lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], 0
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            skipped += 1
    return out, skipped


def query(limit=50, event=None):
    recs, skipped = read_all()
    if event:
        recs = [r for r in recs if r.get("event") == event]
    recs.sort(key=lambda r: r.get("ts", ""), reverse=True)
    return recs[:max(1, min(limit, MAX_LIMIT))], skipped
