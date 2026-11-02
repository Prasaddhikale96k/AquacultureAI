"""Daily JSONL backups, retention, and a downloadable data zip (Track IV F4).

Backups copy only top-level data files (never jobs/, never backups/) into
backend/data/backups/YYYY-MM-DD/. Seven days are kept by default. The export
zip is the same allow-list and is size-capped at 50 MB. No secrets are added:
only files already present in the data directory are copied.
"""
from __future__ import annotations

import io
import os
import shutil
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_EXPORT_BYTES = 50 * 1024 * 1024


class ExportTooLarge(Exception):
    pass


def _data_dir():
    return Path(os.environ.get("AQUA_BACKEND_DATA",
                               Path(__file__).resolve().parents[2] / "data"))


def _backup_root():
    return Path(os.environ.get("AQUA_BACKUP_DIR", _data_dir() / "backups"))


def _env_flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def enabled():
    return _env_flag("AQUA_BACKUP", True)


def export_enabled():
    return _env_flag("AQUA_EXPORT", True)


def _retention_days():
    try:
        return max(1, int(float(os.environ.get("AQUA_BACKUP_RETENTION_DAYS", "7"))))
    except (TypeError, ValueError):
        return 7


def _data_files():
    root = _data_dir()
    if not root.is_dir():
        return []
    out = []
    for p in root.iterdir():
        if not p.is_file():
            continue
        if p.name.endswith((".tmp", ".part")):
            continue
        out.append(p)
    return sorted(out, key=lambda p: p.name)


def _prune(root, now):
    cutoff = datetime.fromtimestamp(now, timezone.utc).date() - timedelta(days=_retention_days())
    pruned = []
    if not root.is_dir():
        return pruned
    for d in root.iterdir():
        if not d.is_dir():
            continue
        try:
            day = datetime.strptime(d.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        if day < cutoff:
            shutil.rmtree(d, ignore_errors=True)
            pruned.append(d.name)
    return pruned


def backup(now=None):
    if not enabled():
        return {"created": False, "reason": "disabled"}
    now = datetime.now(timezone.utc).timestamp() if now is None else float(now)
    day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
    dest = _backup_root() / day
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for src in _data_files():
        try:
            shutil.copy2(src, dest / src.name)
            copied.append(src.name)
        except OSError:
            continue
    pruned = _prune(_backup_root(), now)
    return {"created": True, "dir": str(dest), "files": copied, "pruned": pruned}


def maybe_backup(now=None):
    if not enabled():
        return {"created": False, "reason": "disabled"}
    now = datetime.now(timezone.utc).timestamp() if now is None else float(now)
    day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
    if (_backup_root() / day).is_dir():
        return {"created": False, "reason": "already backed up today", "dir": str(_backup_root() / day)}
    return backup(now)


def export_zip():
    if not export_enabled():
        raise PermissionError("Export is disabled (AQUA_EXPORT=0)")
    files = _data_files()
    total = sum(p.stat().st_size for p in files)
    if total > MAX_EXPORT_BYTES:
        raise ExportTooLarge(f"Export is {total / 1024 / 1024:.1f} MB; limit is 50 MB.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, arcname=p.name)
    return buf.getvalue(), [p.name for p in files]
