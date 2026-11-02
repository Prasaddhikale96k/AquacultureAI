"""Session and CSRF token management with in-memory fast-path and JSONL persistence.

AMENDMENT A4:
Keep an in-memory sessions dict as the middleware's source of truth; persist to
backend/data/sessions.jsonl (append on create; rewrite/compact on startup and on an
hourly expiry sweep). The middleware must NOT read JSONL from disk on every request.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

SESSION_EXPIRY_SECONDS = 7 * 86400  # 7 days

_lock = threading.RLock()
# hashed_token -> {phone, csrf_token, exp, created_at}
_sessions: Dict[str, dict] = {}
_loaded = False


def _data_dir() -> Path:
    return Path(os.environ.get("AQUA_BACKEND_DATA", Path(__file__).resolve().parents[2] / "data"))


def _sessions_file() -> Path:
    return _data_dir() / "sessions.jsonl"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _compact_and_persist(now: float) -> None:
    """Rewrite sessions.jsonl removing expired records."""
    p = _sessions_file()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        active_lines = []
        for h, s in list(_sessions.items()):
            if s.get("exp", 0) > now:
                record = {"token_hash": h, **s}
                active_lines.append(json.dumps(record, ensure_ascii=False))
            else:
                _sessions.pop(h, None)
        p.write_text("\n".join(active_lines) + ("\n" if active_lines else ""), encoding="utf-8")
    except OSError:
        pass


def _ensure_loaded() -> None:
    global _loaded
    with _lock:
        if _loaded:
            return
        p = _sessions_file()
        now = time.time()
        if p.is_file():
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        th = record.get("token_hash")
                        exp = record.get("exp", 0)
                        if th and exp > now:
                            _sessions[th] = {
                                "phone": record.get("phone"),
                                "csrf_token": record.get("csrf_token"),
                                "exp": exp,
                                "created_at": record.get("created_at", now),
                            }
                    except ValueError:
                        continue
            except OSError:
                pass
        _compact_and_persist(now)
        _loaded = True


def create_session(phone: str, now: Optional[float] = None) -> Tuple[str, str]:
    """Create a new 7-day session token and paired CSRF token.

    Returns: (raw_session_token, csrf_token)
    """
    _ensure_loaded()
    now = time.time() if now is None else float(now)
    raw_session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_session_token)
    exp = now + SESSION_EXPIRY_SECONDS

    record = {
        "phone": phone,
        "csrf_token": csrf_token,
        "exp": exp,
        "created_at": now,
    }

    with _lock:
        _sessions[token_hash] = record
        # Append to JSONL file
        p = _sessions_file()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps({"token_hash": token_hash, **record}, ensure_ascii=False) + "\n"
            with p.open("a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass

    return raw_session_token, csrf_token


def validate_session(raw_session_token: str, now: Optional[float] = None) -> Optional[dict]:
    """Fast in-memory validation of session token (source of truth is _sessions dict)."""
    if not raw_session_token:
        return None
    _ensure_loaded()
    now = time.time() if now is None else float(now)
    token_hash = _hash_token(raw_session_token)

    with _lock:
        sess = _sessions.get(token_hash)
        if not sess:
            return None
        if now > sess.get("exp", 0):
            _sessions.pop(token_hash, None)
            return None
        return sess


def revoke_session(raw_session_token: str) -> bool:
    """Revoke session token on logout."""
    if not raw_session_token:
        return False
    _ensure_loaded()
    token_hash = _hash_token(raw_session_token)
    with _lock:
        existed = _sessions.pop(token_hash, None)
        if existed:
            _compact_and_persist(time.time())
            return True
    return False


def active_count(now: Optional[float] = None) -> int:
    """Number of unexpired sessions (no token data returned)."""
    _ensure_loaded()
    now = time.time() if now is None else float(now)
    with _lock:
        return sum(1 for s in _sessions.values() if float(s.get("exp") or 0) > now)


def clear_sessions() -> None:
    """Test helper to clear sessions."""
    global _loaded
    with _lock:
        _sessions.clear()
        _loaded = False
