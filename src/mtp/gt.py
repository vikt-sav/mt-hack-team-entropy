from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

_LAT_M = 111_132.0
_PAT = re.compile(r"POINT \(([-\d.eE+]+) ([-\d.eE+]+)\)")


def _lon_m(lat0: float) -> float:
    return 111_320.0 * np.cos(np.deg2rad(lat0))


def parse_geom(series: pd.Series) -> pd.DataFrame:
    pts = series.fillna("").astype(str).str.extract(_PAT)
    return pd.DataFrame(
        {
            "stop_lon": pd.to_numeric(pts[0], errors="coerce"),
            "stop_lat": pd.to_numeric(pts[1], errors="coerce"),
        }
    )


def _to_epoch_s(series: pd.Series) -> pd.Series:
    return series.astype("datetime64[ns]").astype("int64") // 10**9


def load_traffic(path: Path | str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["event_time"], low_memory=False)
    df = df.sort_values(["tr_id", "event_time"]).reset_index(drop=True)
    df["ts"] = _to_epoch_s(df["event_time"])
    return df


def load_schedule(path: Path | str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["time_begin"])
    if "time_fact_begin" in df.columns:
        df["time_fact_begin"] = pd.to_datetime(df["time_fact_begin"], errors="coerce")
    geom = parse_geom(df["geom"])
    df["stop_lon"] = geom["stop_lon"]
    df["stop_lat"] = geom["stop_lat"]
    df = df.sort_values(["tr_id", "time_begin"]).reset_index(drop=True)
    df["plan_s"] = _to_epoch_s(df["time_begin"])
    return df


def load_points(path: Path | str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["T"] = pd.to_datetime(df["T"])
    df["target_time_begin"] = pd.to_datetime(df["target_time_begin"])
    df["T_s"] = _to_epoch_s(df["T"])
    df["target_s"] = _to_epoch_s(df["target_time_begin"])
    return df


def haversine_m(lat1, lon1, lat2, lon2) -> np.ndarray:
    lat1r, lon1r = np.radians(np.asarray(lat1, dtype=float)), np.radians(np.asarray(lon1, dtype=float))
    lat2r, lon2r = np.radians(np.asarray(lat2, dtype=float)), np.radians(np.asarray(lon2, dtype=float))
    dlat = lat2r - lat1r
    dlon = lon2r - lon1r
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2) ** 2
    return 6_371_000.0 * 2 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def lonlat_to_xy(lat: np.ndarray, lon: np.ndarray, lat0: float, lon0: float):
    return (lat - lat0) * _LAT_M, (lon - lon0) * _lon_m(lat0)


def reconstruct_stop_matches(
    gps_xy: np.ndarray,
    gps_t: np.ndarray,
    stop_xy: np.ndarray,
    stop_plan_s: np.ndarray,
    stop_ids: np.ndarray,
    radius_m: float = 70.0,
    window_s: float = 900.0,
) -> pd.DataFrame:
    """Match GPS points to planned stop arrivals; returns per stop: delay estimate.

    gps_t / stop_plan_s are unix seconds. Matching restricted to |t - plan| <= window_s.
    """
    from scipy.spatial import cKDTree

    n = len(stop_plan_s)
    out = pd.DataFrame(
        {
            "tt_action_item_id": stop_ids,
            "plan_s": stop_plan_s,
            "est_delay_s": np.full(n, np.nan),
            "matched": np.zeros(n, dtype=np.int8),
        }
    )
    if len(gps_t) == 0 or n == 0:
        return out
    tree = cKDTree(gps_xy)
    for i in range(n):
        cand = tree.query_ball_point(stop_xy[i], radius_m)
        if not cand:
            continue
        cand = np.asarray(cand)
        dt = gps_t[cand] - stop_plan_s[i]
        mask = np.abs(dt) <= window_s
        if not mask.any():
            continue
        dt_m = dt[mask]
        out.iloc[i, out.columns.get_loc("est_delay_s")] = float(dt_m[np.argmin(np.abs(dt_m))])
        out.iloc[i, out.columns.get_loc("matched")] = 1
    return out
