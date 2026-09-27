from __future__ import annotations

import numpy as np

from ..features.spec import CATEGORICAL_FEATURES, FEATURES


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if mask.sum() == 0:
        return float("nan")
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask])))


def _features_frame(df) -> np.ndarray:
    x = df[FEATURES].copy()
    for col in CATEGORICAL_FEATURES:
        x[col] = x[col].astype(str)
    return x


def evaluate(model, valid_df, train_df) -> dict:
    y = valid_df["y"].to_numpy(dtype=float)
    pred = model.predict(_features_frame(valid_df))
    persistence = valid_df["delay_s"].to_numpy(dtype=float)

    out = {
        "mae_model": mae(y, pred),
        "mae_persistence": mae(y, persistence),
        "mae_model_event": np.nan,
        "mae_persistence_event": np.nan,
        "event_rate": 0.0,
    }
    events = np.abs(y) > 180.0
    if events.sum() > 0:
        out["mae_model_event"] = mae(y[events], pred[events])
        out["mae_persistence_event"] = mae(y[events], persistence[events])
        out["event_rate"] = float(events.mean())
    if np.isfinite(out["mae_persistence"]) and out["mae_persistence"] > 0:
        out["improvement_pct"] = 100.0 * (1.0 - out["mae_model"] / out["mae_persistence"])
    else:
        out["improvement_pct"] = float("nan")
    return out


def print_report(report: dict) -> None:
    print("=== backtest report ===")
    for key, value in report.items():
        if isinstance(value, float):
            print(f"{key:36s} {value:10.2f}")
        else:
            print(f"{key:36s} {value}")
