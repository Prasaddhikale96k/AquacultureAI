#!/usr/bin/env python3
"""Diagnose vision/LLM API keys (stdlib only).

Reads root .env (simple KEY=VALUE, ignore comments); process env always wins.
Sends one tiny request per provider/mode and prints a per-call verdict.
Never prints full keys (first4...last4 only).
"""
import argparse
import base64
import json
import os
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

CUSTOM_UA = "AquacultureAI-diag/1.0"   # F2 experiment: Cloudflare may block the default UA

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
TIMEOUT = 25


def load_env():
    env = dict(os.environ)  # process env wins
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k.startswith("export "):
                k = k[len("export "):].strip()
            if not k or not k.replace("_", "").isalnum() or k[0].isdigit():
                continue
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                v = v[1:-1]
            env.setdefault(k, v)  # do not overwrite process env
    return env


def key4(k):
    if not k:
        return "<unset>"
    return f"{k[:4]}...{k[-4:]}"


def http_post(url, payload, headers, timeout):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, dict(resp.headers), body, round((time.perf_counter() - t0) * 1000)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, dict(e.headers), body, round((time.perf_counter() - t0) * 1000)
    except Exception as e:
        return None, {}, f"{type(e).__name__}: {e}", round((time.perf_counter() - t0) * 1000)


def verdict(status, body):
    if status == 200:
        return "OK"
    b = (body or "").lower()
    if status in (401, 403):
        return "KEY_INVALID"
    if status == 404 or "model_not_found" in b or "deprecated" in b:
        return "MODEL_GONE"
    if status == 429:
        return "QUOTA_EXHAUSTED"
    if status is None:
        return "NETWORK_ERROR"
    return f"HTTP_{status}"


def make_1x1_png():
    raw = b"\x00" + b"\xff\x00\x00"  # filter byte + red RGB pixel
    compressed = zlib.compress(raw)

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        crc = zlib.crc32(t + d) & 0xFFFFFFFF
        return c + struct.pack(">I", crc)

    sig = b"\x89PNG\r\n\x1a\n"
    return (
        sig
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


ALL_CALLS = ("groq-vision", "groq-text", "gemini-vision", "gemini-text")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Diagnose vision/LLM API keys (stdlib only).")
    ap.add_argument("--only", default="", help="comma list of: " + ", ".join(ALL_CALLS))
    ap.add_argument("--groq-ua", choices=("default", "custom"), default="default",
                    help="default = python-urllib UA; custom = 'AquacultureAI-diag/1.0'")
    args = ap.parse_args(argv)
    only = {s.strip() for s in args.only.split(",") if s.strip()} or set(ALL_CALLS)

    env = load_env()
    groq_key = env.get("GROQ_API_KEY") or ""
    gemini_key = env.get("GEMINI_API_KEY") or ""
    groq_vision_model = env.get("GROQ_VISION_MODEL") or "meta-llama/llama-4-scout-17b-16e-instruct"
    groq_model = env.get("GROQ_MODEL") or "openai/gpt-oss-120b"
    gemini_vision_model = env.get("GEMINI_VISION_MODEL") or "gemini-2.5-flash"
    gemini_model = env.get("GEMINI_MODEL") or "gemini-2.5-flash"
    groq_headers = {"Authorization": f"Bearer {groq_key}"}
    if args.groq_ua == "custom":
        groq_headers["User-Agent"] = CUSTOM_UA

    png = make_1x1_png()
    b64 = base64.b64encode(png).decode("ascii")

    print(f"env file present={ENV_FILE.is_file()} (process env wins over .env); groq_ua={args.groq_ua}")
    print(f"GROQ_API_KEY      : {key4(groq_key)}")
    print(f"GEMINI_API_KEY    : {key4(gemini_key)}")
    print(f"GROQ_VISION_MODEL : {groq_vision_model}")
    print(f"GROQ_MODEL        : {groq_model}")
    print(f"GEMINI_VISION_MODEL: {gemini_vision_model}")
    print(f"GEMINI_MODEL      : {gemini_model}")
    print()

    calls = []

    # ---- Groq vision
    if "groq-vision" in only:
        if groq_key:
            url = "https://api.groq.com/openai/v1/chat/completions"
            payload = {
                "model": groq_vision_model,
                "temperature": 0.1,
                "max_tokens": 2000,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": 'Return exactly {"detections": []}.'},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
                ]}],
            }
            status, hdrs, body, ms = http_post(url, payload, groq_headers, TIMEOUT)
            calls.append(("groq-vision", status, ms, hdrs, body))
        else:
            calls.append(("groq-vision", None, 0, {}, "key unset"))

    # ---- Groq text
    if "groq-text" in only:
        if groq_key:
            url = "https://api.groq.com/openai/v1/chat/completions"
            payload = {"model": groq_model, "temperature": 0.2, "max_tokens": 50,
                       "messages": [{"role": "user", "content": "Say hi."}]}
            status, hdrs, body, ms = http_post(url, payload, groq_headers, TIMEOUT)
            calls.append(("groq-text", status, ms, hdrs, body))
        else:
            calls.append(("groq-text", None, 0, {}, "key unset"))

    # ---- Gemini vision
    if "gemini-vision" in only:
        if gemini_key:
            url = ("https://generativelanguage.googleapis.com/v1beta/models/"
                   + urllib.parse.quote(gemini_vision_model, safe="")
                   + ":generateContent?key=" + urllib.parse.quote(gemini_key, safe=""))
            payload = {
                "contents": [{"role": "user", "parts": [
                    {"text": 'Return exactly {"detections": []}.'},
                    {"inlineData": {"mimeType": "image/png", "data": b64}},
                ]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2000},
            }
            status, hdrs, body, ms = http_post(url, payload, {}, TIMEOUT)
            calls.append(("gemini-vision", status, ms, hdrs, body))
        else:
            calls.append(("gemini-vision", None, 0, {}, "key unset"))

    # ---- Gemini text
    if "gemini-text" in only:
        if gemini_key:
            url = ("https://generativelanguage.googleapis.com/v1beta/models/"
                   + urllib.parse.quote(gemini_model, safe="")
                   + ":generateContent?key=" + urllib.parse.quote(gemini_key, safe=""))
            payload = {
                "contents": [{"role": "user", "parts": [{"text": "Say hi."}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 50},
            }
            status, hdrs, body, ms = http_post(url, payload, {}, TIMEOUT)
            calls.append(("gemini-text", status, ms, hdrs, body))
        else:
            calls.append(("gemini-text", None, 0, {}, "key unset"))

    for name, status, ms, hdrs, body in calls:
        v = verdict(status, body)
        print(f"=== {name} ===")
        print(f"status={status} latency_ms={ms} verdict={v}")
        if status is not None:
            rl = {k: vv for k, vv in hdrs.items()
                  if k.lower().startswith("x-ratelimit") or k.lower() == "retry-after"}
            print(f"headers={rl}")
        err = "" if status in (200, None) else (body or "")[:300]
        print(f"error={err}")
        print(f"VERDICT: {v}")
        print()


if __name__ == "__main__":
    main()
