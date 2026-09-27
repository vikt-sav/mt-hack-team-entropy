from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool

from ..features.spec import CATEGORICAL_FEATURES, FEATURES
from .backtest import evaluate


def time_split(ds: pd.DataFrame, valid_fraction: float = 0.2) -> tuple[pd.DataFrame, pd.DataFrame]:
    cutoff = ds["ts"].quantile(1.0 - valid_fraction)
    train = ds[ds["ts"] < cutoff]
    valid = ds[ds["ts"] >= cutoff]
    return train, valid


def _make_pool(df: pd.DataFrame, label: bool = True) -> Pool:
    x = df[FEATURES].copy()
    for col in CATEGORICAL_FEATURES:
        x[col] = x[col].astype(str)
    return Pool(x, df["y"] if label else None, cat_features=CATEGORICAL_FEATURES)


def train_models(
    ds: pd.DataFrame,
    out_dir: Path | str,
    iterations: int = 600,
    depth: int = 6,
    learning_rate: float = 0.06,
    quantiles: list[float] | None = None,
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    train, valid = time_split(ds)

    params = dict(
        iterations=iterations,
        depth=depth,
        learning_rate=learning_rate,
        loss_function="MAE",
        verbose=False,
        allow_writing_files=False,
        random_seed=42,
    )
    model = CatBoostRegressor(**params)
    model.fit(_make_pool(train), eval_set=_make_pool(valid))
    model.save_model(str(out_dir / "predictor.cbm"))

    quantile_metrics: dict = {}
    for q in quantiles or []:
        qm = CatBoostRegressor(**{**params, "loss_function": f"Quantile:alpha={q}"})
        qm.fit(_make_pool(train), eval_set=_make_pool(valid))
        qm.save_model(str(out_dir / f"quantile_{int(q * 100)}.cbm"))
        scores = qm.get_best_score().get("validation", {})
        value = scores.get("MAE")
        if value is None and scores:
            value = next(iter(scores.values()))
        quantile_metrics[str(q)] = float(value) if value is not None else float("nan")

    train_pool, valid_pool = _make_pool(train), _make_pool(valid)
    metrics = evaluate(model, valid, train)
    report = {
        "valid_mae_model_s": metrics["mae_model"],
        "valid_mae_persistence_s": metrics["mae_persistence"],
        "improvement_pct": metrics["improvement_pct"],
        "valid_mae_model_event_s": metrics["mae_model_event"],
        "valid_mae_persistence_event_s": metrics["mae_persistence_event"],
        "event_rate": metrics["event_rate"],
        "n_train": int(len(train)),
        "n_valid": int(len(valid)),
        "cutoff": str(train["ts"].max()),
        "quantile_valid_mae": quantile_metrics,
    }
    (out_dir / "metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    meta = {
        "features": FEATURES,
        "categorical": CATEGORICAL_FEATURES,
        "horizon_s": None,
        "trained_at": pd.Timestamp.utcnow().isoformat(),
        "report": report,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return report


def feature_importance(model_path: Path | str) -> dict:
    model = CatBoostRegressor()
    model.load_model(str(model_path))
    names = model.feature_names_
    values = model.get_feature_importance()
    return dict(sorted(zip(names, values), key=lambda kv: -kv[1]))
