"""Minimal .env loader (stdlib only; python-dotenv is not a dependency).

Reads KEY=value lines from the project-root `.env` file into os.environ.
Rules:
- Blank lines and `#` comments are skipped. Surrounding single/double quotes
  on values are stripped. `export KEY=value` prefix is tolerated.
- Process environment always wins: keys already set in os.environ are never
  overwritten by the file.
- Only files you create yourself are read; nothing is ever written, logged,
  or sent anywhere by this module.
"""
import os
from pathlib import Path


def load_dotenv(path=None):
    """Load `.env` into os.environ (missing keys only). Returns {key: source}.

    `source` is "env" for pre-existing process variables, "file" for values
    taken from the dotenv file. Values are never included in the return.
    Missing/unreadable file -> {} (never raises).
    """
    p = Path(path) if path else Path(__file__).resolve().parents[1] / ".env"
    loaded = {}
    for k in list(os.environ):
        loaded[k] = "env"
    try:
        # utf-8-sig strips a BOM when present (e.g. .env saved by PowerShell
        # Set-Content) and behaves like utf-8 otherwise.
        text = p.read_text(encoding="utf-8-sig")
    except OSError:
        return {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key not in os.environ:
            os.environ[key] = value
            loaded[key] = "file"
    return loaded
