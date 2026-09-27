from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

from mtp.config import Settings
from mtp.model.backtest import print_report
from mtp.model.dataset import build_dataset, raw_to_samples, read_raw
from mtp.model.train import feature_importance, train_models
from mtp.schedule.adapter import load_timetable


def run(cmd: list[str]) -> None:
    print(f"[smoke] $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=str(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--routes", type=int, default=4)
    ap.add_argument("--hours", type=float, default=4.0)
    ap.add_argument("--speed", type=float, default=600.0)
    ap.add_argument("--iterations", type=int, default=300)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        sched = tmp / "schedule.csv"
        raw = tmp / "raw"
        raw.mkdir()

        start_h = 6
        end_h = 6 + int(args.hours)
        run(
            [
                sys.executable, "-m", "tools.synthetic.gen_schedule",
                "--out", str(sched),
                "--routes", str(args.routes),
                "--headway-min", "8",
                "--start", f"{start_h:02d}:00",
                "--end", f"{end_h:02d}:00",
            ]
        )
        run(
            [
                sys.executable, "-m", "tools.synthetic.emu_ndtp",
                "--schedule", str(sched),
                "--out", str(tmp / "sim.jsonl"),
                "--tick-s", "10",
                "--speed", str(args.speed),
                "--seed", "11",
            ]
        )

        from mtp.ingest.parser import NDTPParser

        parser = NDTPParser(ROOT / "config" / "ndtp_fields.yaml")
        import pyarrow as pa
        import pyarrow.parquet as pq

        from mtp.ingest.recorder import _SCHEMA

        rows = []
        with open(tmp / "sim.jsonl", encoding="utf-8") as f:
            for line in f:
                recs = parser.parse(line.encode("utf-8"))
                for rec in recs:
                    rows.append(
                        {
                            "vehicle_id": rec.vehicle_id,
                            "ts": rec.ts,
                            "lat": rec.lat,
                            "lon": rec.lon,
                            "speed": rec.speed,
                            "heading": rec.heading,
                            "route_id": rec.route_id,
                            "direction_id": rec.direction_id,
                            "trip_id": rec.trip_id,
                        }
                    )
        table = pa.Table.from_pylist(rows, schema=_SCHEMA)
        pq.write_table(table, raw / "stream_smoke.parquet")
        print(f"[smoke] raw records: {len(rows)}")

        settings = Settings.load()
        settings.schedule["path"] = str(sched)
        settings.target["horizon_s"] = 600

        tt = load_timetable(sched, settings.schedule.get("columns"))
        raw_df = read_raw(raw)
        samples = raw_to_samples(raw_df, tt, settings)
        err = samples["delay_s"].abs()
        print(f"[smoke] matched: {len(samples)}, delay median |err|={err.median():.1f}s, p95={err.quantile(0.95):.1f}s")

        ds = build_dataset(samples, settings, tt)
        print(f"[smoke] dataset rows: {len(ds)}, event rate: {(ds['y'].abs() > 180).mean():.3f}")
        dataset_path = tmp / "dataset.parquet"
        ds.to_parquet(dataset_path, index=False)

        report = train_models(ds, tmp / "models", iterations=args.iterations, quantiles=None)
        print_report(report)
        imp = feature_importance(tmp / "models" / "predictor.cbm")
        print("=== top-8 features ===")
        for name, value in list(imp.items())[:8]:
            print(f"{name:24s} {value:6.2f}")

        ok = report["improvement_pct"] > 10.0
        print(f"[smoke] RESULT: improvement over persistence = {report['improvement_pct']:.1f}% -> {'OK' if ok else 'WEAK'}")


if __name__ == "__main__":
    main()
