"""Gated DO forecasting experiment (v1 is NOT enabled in the product).

Refuses to train unless a real dissolved-oxygen dataset exists:
  AQUA_DO_CSV pointing to a CSV with columns: timestamp, do_mg_l
  and at least 30 days of hourly-or-finer data.

Usage:
  python scripts/predict_do_lstm.py --csv data/do_history.csv --out models/do_lstm.pt
Exit code 0 with SKIPPED message when data is insufficient (safe default).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

MIN_DAYS = 30
MIN_ROWS = MIN_DAYS * 24


def load_csv(path: Path):
    import pandas as pd

    df = pd.read_csv(path)
    cols = {c.lower().strip(): c for c in df.columns}
    tcol = cols.get("timestamp") or cols.get("time") or cols.get("created_at")
    vcol = cols.get("do_mg_l") or cols.get("do") or cols.get("dissolved_oxygen")
    if not tcol or not vcol:
        raise SystemExit("SKIPPED: CSV needs timestamp and do_mg_l columns")
    df = df[[tcol, vcol]].rename(columns={tcol: "ts", vcol: "do"})
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce", utc=True)
    df["do"] = pd.to_numeric(df["do"], errors="coerce")
    df = df.dropna().sort_values("ts").drop_duplicates("ts")
    return df.set_index("ts")["do"]


def gate(series) -> tuple[bool, str]:
    if len(series) < MIN_ROWS:
        return False, f"SKIPPED: {len(series)} rows < {MIN_ROWS} (need ~{MIN_DAYS} days hourly)"
    span_days = (series.index[-1] - series.index[0]).total_seconds() / 86400
    if span_days < MIN_DAYS:
        return False, f"SKIPPED: span {span_days:.1f} days < {MIN_DAYS} days"
    median_gap = series.index.to_series().diff().dt.total_seconds().median()
    if median_gap is None or median_gap > 3600:
        return False, f"SKIPPED: median gap {median_gap}s > 3600s"
    return True, f"OK: {len(series)} rows / {span_days:.1f} days"


def train(series, out: Path, epochs: int = 30, window: int = 24):
    import numpy as np
    import torch
    from torch import nn

    values = series.to_numpy(dtype="float32")
    mean, std = float(values.mean()), float(values.std() or 1.0)
    values = (values - mean) / std

    xs, ys = [], []
    for i in range(len(values) - window):
        xs.append(values[i:i + window])
        ys.append(values[i + window])
    x = torch.tensor(np.array(xs), dtype=torch.float32).unsqueeze(-1)
    y = torch.tensor(np.array(ys), dtype=torch.float32).unsqueeze(-1)

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(1, 32, batch_first=True)
            self.head = nn.Linear(32, 1)

        def forward(self, z):
            out, _ = self.lstm(z)
            return self.head(out[:, -1])

    model = Net()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.MSELoss()
    for _ in range(epochs):
        opt.zero_grad()
        loss = loss_fn(model(x), y)
        loss.backward()
        opt.step()

    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "mean": mean, "std": std, "window": window}, out)
    return {"rows": int(len(values)), "window": window, "epochs": epochs, "out": str(out),
            "final_loss": round(float(loss.item()), 6),
            "note": "EXPERIMENTAL. Product v1 uses the transparent proxy in backend/predict.py."}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.getenv("AQUA_DO_CSV", "data/do_history.csv"))
    ap.add_argument("--out", default="models/do_lstm.pt")
    ap.add_argument("--epochs", type=int, default=30)
    args = ap.parse_args()

    path = Path(args.csv)
    if not path.is_file():
        print(json.dumps({"status": "SKIPPED", "reason": f"missing dataset: {path}"}, ensure_ascii=False))
        return 0
    try:
        series = load_csv(path)
    except SystemExit as exc:
        print(json.dumps({"status": "SKIPPED", "reason": str(exc)}, ensure_ascii=False))
        return 0
    ok, reason = gate(series)
    if not ok:
        print(json.dumps({"status": "SKIPPED", "reason": reason}, ensure_ascii=False))
        return 0
    result = train(series, Path(args.out), epochs=args.epochs)
    print(json.dumps({"status": "TRAINED", **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
