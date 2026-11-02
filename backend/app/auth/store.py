"""JSONL user storage for AquacultureAI."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

_lock = threading.RLock()
_users_cache: Dict[str, dict] = {}
_loaded = False


def _data_dir() -> Path:
    return Path(os.environ.get("AQUA_BACKEND_DATA", Path(__file__).resolve().parents[2] / "data"))


def _users_file() -> Path:
    return _data_dir() / "users.jsonl"


def _ensure_loaded() -> None:
    global _loaded
    with _lock:
        if _loaded:
            return
        p = _users_file()
        if p.is_file():
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        ph = record.get("phone")
                        if ph:
                            _users_cache[ph] = record
                    except ValueError:
                        continue
            except OSError:
                pass
        _loaded = True


def get_user(phone: str) -> Optional[dict]:
    """Retrieve user record by normalized phone number."""
    _ensure_loaded()
    with _lock:
        return _users_cache.get(phone)


def save_user(user: dict) -> dict:
    """Save or update user in memory and append to backend/data/users.jsonl."""
    _ensure_loaded()
    phone = user.get("phone")
    if not phone:
        raise ValueError("User must have a normalized phone number")

    now = time.time()
    with _lock:
        existing = _users_cache.get(phone, {})
        merged = {**existing, **user, "updated_at": now}
        if "created_at" not in merged:
            merged["created_at"] = now
        _users_cache[phone] = merged

        # Append to JSONL file
        p = _users_file()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(merged, ensure_ascii=False) + "\n")
        except OSError:
            pass

        return merged


def list_users() -> List[dict]:
    """Return all registered users."""
    _ensure_loaded()
    with _lock:
        return list(_users_cache.values())


def clear_store() -> None:
    """Test helper to clear users cache."""
    global _loaded
    with _lock:
        _users_cache.clear()
        _loaded = False
