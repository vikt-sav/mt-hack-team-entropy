"""Trains the STREAMING model: cur_dev_s is our own GPS-based estimate."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

CAT_FEATURES = ["tr_id", "target_stop_id", "stop_key"]
DROP = {"sample_id", "T", "target_s", "target_delay_s", "target_class"}
TARGET = "target_delay_s"


def load(name: str) -> pd.DataFrame:
    df = pd.read_parquet(f"data/gt/features_stream_{name}.parquet")
    for c in CAT_FEATURES:
        df[c] = df[c].astype(str)
    return df


def main() -> None:
    train, test = load("train"), load("test")
    cols = [c for c in train.columns if c not in DROP]
    num = [c for c in cols if c not in CAT_FEATURES]
    train[num] = train[num].apply(pd.to_numeric, errors="coerce")
    test[num] = test[num].apply(pd.to_numeric, errors="coerce")

    Xtr, ytr = train[cols], train[TARGET].astype(float)
    Xte, yte = test[cols], test[TARGET].astype(float)
    mae_zero = float(np.mean(np.abs(yte)))
    mae_cur = float(np.mean(np.abs(yte - Xte["cur_dev_s"].astype(float))))
    print(f"[stream-train] test baselines: zero={mae_zero:.1f}, est_dev as cur={mae_cur:.1f}")

    model = CatBoostRegressor(
        iterations=3000, learning_rate=0.05, depth=6, loss_function="MAE",
        eval_metric="MAE", random_seed=42, verbose=1000, allow_writing_files=False, l2_leaf_reg=3.0,
    )
    model.fit(Pool(Xtr, ytr, cat_features=CAT_FEATURES), eval_set=Pool(Xte, yte, cat_features=CAT_FEATURES), use_best_model=True)
    pred = model.predict(Xte)
    mae = float(np.mean(np.abs(yte - pred)))
    print(f"[stream-train] TEST MAE = {mae:.1f} (model with delay hint: 40.9)")

    out = Path("data/gt/models")
    model.save_model(str(out / "catboost_stream.cbm"))
    meta = {"features": cols, "cat": CAT_FEATURES, "test_mae": mae, "kind": "streaming"}
    (out / "meta_stream.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    imp = model.get_feature_importance()
    for i in np.argsort(-imp)[:10]:
        print(f"  {cols[i]:26s} {imp[i]:6.2f}")


if __name__ == "__main__":
    main()
