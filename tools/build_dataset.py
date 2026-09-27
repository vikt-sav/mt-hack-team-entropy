from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mtp.config import Settings
from mtp.model.dataset import build_dataset, raw_to_samples, read_raw
from mtp.schedule.adapter import load_timetable


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--schedule", default=None)
    ap.add_argument("--settings", default=None)
    ap.add_argument("--out", default="data/dataset.parquet")
    args = ap.parse_args()

    settings = Settings.load(args.settings)
    sched_path = args.schedule or settings.schedule["path"]
    tt = load_timetable(sched_path, settings.schedule.get("columns"))
    print(f"[dataset] schedule loaded: {len(tt.trips)} trips, {len(tt.routes())} routes")

    raw = read_raw(args.raw)
    print(f"[dataset] raw records: {len(raw)}")
    samples = raw_to_samples(raw, tt, settings)
    print(f"[dataset] matched samples: {len(samples)}")

    ds = build_dataset(samples, settings, tt)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ds.to_parquet(out, index=False)
    print(f"[dataset] saved {len(ds)} rows -> {out}")
    print(f"[dataset] event rate |y|>3min: {(ds['y'].abs() > 180).mean():.3f}")


if __name__ == "__main__":
    main()
