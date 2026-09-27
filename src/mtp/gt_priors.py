"""Builds per-physical-stop delay priors from schedule facts.

Stops are keyed by rounded coordinates because tt_action_item_id is unique
per planned arrival. Leave-one-vehicle-out variant for labeled rows.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

COORD_DP = 5


def add_stop_key(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    lat = pd.to_numeric(df.get("stop_lat"), errors="coerce")
    lon = pd.to_numeric(df.get("stop_lon"), errors="coerce")
    df["stop_key"] = (
        lat.round(COORD_DP).astype(str)
        + "_"
        + lon.round(COORD_DP).astype(str)
    )
    return df


def build_stop_priors(schedule: pd.DataFrame) -> pd.DataFrame:
    sc = add_stop_key(schedule)
    sc = sc.dropna(subset=["time_fact_begin"]).copy()
    sc["dev"] = (sc["time_fact_begin"] - sc["time_begin"]).dt.total_seconds()
    sc = sc[sc["dev"].abs() <= 1200]
    g = sc.groupby("stop_key")["dev"]
    priors = pd.DataFrame(
        {
            "prior_n": g.count(),
            "prior_sum": g.sum(),
            "prior_median": g.median(),
        }
    ).reset_index()
    return priors


def attach_priors(
    points: pd.DataFrame,
    priors: pd.DataFrame,
    target_col: str | None = None,
) -> pd.DataFrame:
    """Adds prior features keyed by physical stop.

    Labeled rows (target_col given) get LOO values: own fact removed from the
    aggregate so the label never leaks into features.
    """
    df = add_stop_key(points)
    df = df.merge(
        priors.rename(columns={"stop_key": "pk"}),
        left_on="stop_key",
        right_on="pk",
        how="left",
    )
    df = df.drop(columns=["pk"])
    if target_col is not None and target_col in df.columns:
        own = pd.to_numeric(df[target_col], errors="coerce")
        n_all = df["prior_n"].fillna(0)
        sum_all = df["prior_sum"].fillna(0.0)
        n_others = (n_all - 1).clip(lower=0)
        sum_others = (sum_all - own.fillna(0.0)).where(n_all > 0, np.nan)
        df["prior_n"] = np.where(n_all > 0, n_others, np.nan)
        df["prior_sum"] = np.where(n_all > 0, sum_others, np.nan)
        df["prior_mean"] = np.where(n_others > 0, sum_others / n_others.replace(0, np.nan), np.nan)
        df["prior_median"] = np.nan
    else:
        df["prior_mean"] = df["prior_sum"] / df["prior_n"].replace(0, np.nan)
    df["prior_known"] = df["prior_n"].notna().astype(float)
    return df
