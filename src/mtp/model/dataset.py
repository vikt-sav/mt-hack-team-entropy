from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import Settings
from ..matching.delay import DelayEstimator
from ..schemas import TelemetryRecord

SAMPLE_COLUMNS = [
    "vehicle_id",
    "ts",
    "route_id",
    "direction_id",
    "trip_id",
    "along_m",
    "offset_m",
    "speed",
    "delay_s",
    "next_stop_m",
]


def read_raw(raw_dir: Path | str) -> pd.DataFrame:
    import pyarrow.parquet as pq

    files = sorted(Path(raw_dir).glob("stream_*.parquet"))
    if not files:
        raise FileNotFoundError(f"no stream parquet files in {raw_dir}")
    dfs = []
    for f in files:
        try:
            dfs.append(pq.read_table(f).to_pandas())
        except Exception as exc:
            print(f"[dataset] skipping {f.name}: {exc}")
    if not dfs:
        raise ValueError("no readable parquet files")
    df = pd.concat(dfs, ignore_index=True)
    df = df.drop_duplicates(subset=["vehicle_id", "ts"]).sort_values("ts")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def raw_to_samples(df: pd.DataFrame, tt, settings: Settings) -> pd.DataFrame:
    estimator = DelayEstimator(tt, max_offset_m=float(settings.target["max_lateral_offset_m"]))
    records = [
        TelemetryRecord(
            vehicle_id=str(r.vehicle_id),
            ts=r.ts.to_pydatetime(),
            lat=float(r.lat),
            lon=float(r.lon),
            speed=float(r.speed),
            heading=float(r.heading),
            route_id=None if pd.isna(r.route_id) else str(r.route_id),
            direction_id=None if pd.isna(r.direction_id) else str(r.direction_id),
            trip_id=None if pd.isna(r.trip_id) else str(r.trip_id),
        )
        for r in df.itertuples(index=False)
    ]
    matched = estimator.match_all(records)
    if not matched:
        raise ValueError("matching produced no samples")
    return pd.DataFrame([asdict(s) for s in matched])[SAMPLE_COLUMNS]


def build_dataset(samples: pd.DataFrame, settings: Settings, tt) -> pd.DataFrame:
    grid_s = int(settings.target["grid_s"])
    steps = max(int(round(int(settings.target["horizon_s"]) / grid_s)), 1)
    clip_lo = float(settings.target["delay_clip_min_s"])
    clip_hi = float(settings.target["delay_clip_max_s"])

    out_frames = []
    for (vid, route, direction), g in samples.groupby(
        ["vehicle_id", "route_id", "direction_id"], sort=False
    ):
        g = g.sort_values("ts").drop_duplicates(subset="ts").set_index("ts")
        if len(g) < steps + 12:
            continue
        start, end = g.index.min(), g.index.max()
        if (end - start).total_seconds() < (steps + 10) * grid_s:
            continue
        grid = pd.date_range(start.ceil(f"{grid_s}s"), end.floor(f"{grid_s}s"), freq=f"{grid_s}s")
        if len(grid) < steps + 10:
            continue
        r = g.reindex(grid).ffill(limit=3)
        delay = r["delay_s"].astype(float)
        feats = pd.DataFrame(index=range(len(grid)))
        feats["vehicle_id"] = vid
        feats["ts"] = grid
        feats["route_id"] = route
        feats["direction_id"] = direction
        trip_col = r["trip_id"].ffill().bfill()
        feats["trip_id"] = trip_col.astype(str).values
        feats["delay_s"] = delay.values
        feats["delay_mean_5m"] = delay.rolling(10, min_periods=3).mean().values
        feats["delay_slope_5m"] = ((delay - delay.shift(10)) / 5.0).values
        feats["delay_slope_10m"] = ((delay - delay.shift(20)) / 10.0).values
        feats["speed"] = r["speed"].astype(float).values
        feats["offset_m"] = r["offset_m"].astype(float).values
        max_along = float(r["along_m"].max())
        if max_along > 1.0:
            feats["along_frac"] = (r["along_m"].astype(float) / max_along).values
        else:
            feats["along_frac"] = 0.0
        feats["next_stop_m"] = r["next_stop_m"].astype(float).values
        feats["hour"] = grid.hour.astype(float).values
        feats["minute"] = grid.minute.astype(float).values
        feats["dayofweek"] = grid.dayofweek.astype(float).values
        feats["y"] = delay.shift(-steps).values
        out_frames.append(feats)

    if not out_frames:
        raise ValueError("empty dataset after grid build")
    ds = pd.concat(out_frames, ignore_index=True)
    ds["y"] = ds["y"].clip(clip_lo, clip_hi)
    ds["ts30"] = ds["ts"].dt.floor(f"{grid_s}s")
    ds = _add_headway_features(ds, samples, tt, grid_s)
    ds = _add_route_features(ds, samples, grid_s)
    ds = ds.drop(columns=["ts30"])
    ds = ds.dropna(subset=["y", "delay_s"])
    return ds


def _add_headway_features(
    ds: pd.DataFrame, samples: pd.DataFrame, tt, grid_s: int
) -> pd.DataFrame:
    pairs = list(zip(ds["route_id"], ds["direction_id"]))
    headway_map = {}
    for key in set(pairs):
        value = tt.scheduled_headway_s(key[0], key[1])
        headway_map[key] = value if value else np.nan
    ds["sched_headway_s"] = pd.Series(pairs).map(headway_map).values

    prev_map = {}
    for trip_id in tt.trip_index:
        prev = tt.prev_trip(trip_id)
        if prev is not None:
            prev_map[trip_id] = prev.trip_id
    ds["prev_trip_id"] = ds["trip_id"].map(prev_map)

    ds["prev_trip_delay_s"] = np.nan
    ds["prev_trip_gap_s"] = np.nan
    has_prev = ds["prev_trip_id"].notna()
    if not has_prev.any():
        return ds.drop(columns=["prev_trip_id"])

    s = samples.copy()
    s["ts30"] = s["ts"].dt.floor(f"{grid_s}s")
    prev_side = (
        s.groupby(["trip_id", "ts30"], as_index=False)["delay_s"].mean()
        .rename(columns={"trip_id": "prev_trip_id", "ts30": "prev_ts30", "delay_s": "prev_trip_delay_s"})
        .sort_values("prev_ts30")
    )
    cur = ds.loc[has_prev, ["prev_trip_id", "ts30"]].sort_values("ts30")
    if prev_side.empty or cur.empty:
        return ds.drop(columns=["prev_trip_id"])
    merged = pd.merge_asof(
        cur,
        prev_side,
        left_on="ts30",
        right_on="prev_ts30",
        by="prev_trip_id",
        direction="backward",
        tolerance=pd.Timedelta(f"{grid_s * 3}s"),
    )
    idx = cur.index
    ds.loc[idx, "prev_trip_delay_s"] = merged["prev_trip_delay_s"].values
    gap = (merged["ts30"] - merged["prev_ts30"]).dt.total_seconds()
    ds.loc[idx, "prev_trip_gap_s"] = gap.values
    return ds.drop(columns=["prev_trip_id"])


def _add_route_features(
    ds: pd.DataFrame, samples: pd.DataFrame, grid_s: int
) -> pd.DataFrame:
    s = samples.copy()
    s["ts30"] = s["ts"].dt.floor(f"{grid_s}s")
    agg = (
        s.groupby(["route_id", "direction_id", "ts30"])
        .agg(cnt=("vehicle_id", "nunique"), dmean=("delay_s", "mean"))
        .reset_index()
        .sort_values("ts30")
    )
    grouped = agg.groupby(["route_id", "direction_id"], sort=False)
    agg["count_route_10m"] = grouped["cnt"].transform(lambda x: x.rolling(20, min_periods=1).sum())
    agg["mean_delay_route_5m"] = grouped["dmean"].transform(lambda x: x.rolling(10, min_periods=1).mean())
    agg = agg.drop(columns=["cnt", "dmean"])
    ds = ds.merge(agg, on=["route_id", "direction_id", "ts30"], how="left")
    return ds
