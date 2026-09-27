from __future__ import annotations

NUMERIC_FEATURES = [
    "delay_s",
    "delay_mean_5m",
    "delay_slope_5m",
    "delay_slope_10m",
    "speed",
    "offset_m",
    "along_frac",
    "next_stop_m",
    "sched_headway_s",
    "prev_trip_delay_s",
    "prev_trip_gap_s",
    "count_route_10m",
    "mean_delay_route_5m",
    "hour",
    "minute",
    "dayofweek",
]

CATEGORICAL_FEATURES = ["route_id", "direction_id"]

FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
