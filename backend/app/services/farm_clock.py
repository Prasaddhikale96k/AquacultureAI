"""Farm clock helper (Track II D1 correction C1).

All human-facing time windows (diurnal phase, daily digest, feeding windows,
behaviour hour buckets) use the farm's local timezone, not the server's.
Default is Asia/Kolkata; override with AQUA_FARM_TZ.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_FARM_TZ = "Asia/Kolkata"


def farm_tz_name():
    raw = (os.environ.get("AQUA_FARM_TZ") or "").strip()
    return raw or DEFAULT_FARM_TZ


def farm_tz():
    try:
        return ZoneInfo(farm_tz_name())
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_FARM_TZ)


def farm_now(ts=None):
    stamp = time.time() if ts is None else float(ts)
    return datetime.fromtimestamp(stamp, tz=timezone.utc).astimezone(farm_tz())


def farm_hour(ts=None):
    """Fractional hour in farm-local time (0.0-23.99)."""
    dt = farm_now(ts)
    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0


def farm_day(ts=None):
    return farm_now(ts).date().isoformat()


def farm_time_label(ts=None):
    return farm_now(ts).strftime("%H:%M")
