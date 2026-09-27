from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mtp.model.backtest import print_report
from mtp.model.train import feature_importance, train_models


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="data/dataset.parquet")
    ap.add_argument("--out", default="data/models")
    ap.add_argument("--iterations", type=int, default=600)
    ap.add_argument("--depth", type=int, default=6)
    ap.add_argument("--learning-rate", type=float, default=0.06)
    ap.add_argument("--no-quantiles", action="store_true")
    args = ap.parse_args()

    ds = pd.read_parquet(args.dataset)
    print(f"[train] dataset rows: {len(ds)}")
    quantiles = None if args.no_quantiles else [0.1, 0.9]
    report = train_models(
        ds,
        args.out,
        iterations=args.iterations,
        depth=args.depth,
        learning_rate=args.learning_rate,
        quantiles=quantiles,
    )
    print_report(report)
    print("=== feature importance (top 10) ===")
    for name, value in list(feature_importance(Path(args.out) / "predictor.cbm").items())[:10]:
        print(f"{name:24s} {value:6.2f}")


if __name__ == "__main__":
    main()
