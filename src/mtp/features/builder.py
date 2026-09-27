from __future__ import annotations

from collections import deque
from typing import Callable

import numpy as np

from ..schemas import DelaySample
from ..schedule.timetable import Timetable
from .spec import FEATURES


class LiveFeatureBuilder:
    def __init__(self, tt: Timetable, geometry_fn: Callable[[str, str], object] | None = None):
        self.tt = tt
        self._geometry_fn = geometry_fn
        self._headway_cache: dict[tuple[str, str], float] = {}

    def _sched_headway(self, route_id: str, direction_id: str) -> float:
        key = (route_id, direction_id)
        if key not in self._headway_cache:
            value = self.tt.scheduled_headway_s(route_id, direction_id)
            self._headway_cache[key] = value if value else 600.0
        return self._headway_cache[key]

    def _route_length(self, route_id: str, direction_id: str) -> float:
        if self._geometry_fn is None:
            return 0.0
        geom = self._geometry_fn(route_id, direction_id)
        return geom.length_m if geom is not None else 0.0

    def build(
        self,
        history: deque[DelaySample],
        fleet_samples: dict[str, DelaySample],
        route_samples: dict[tuple[str, str], deque[DelaySample]],
    ) -> dict | None:
        if not history:
            return None
        cur = history[-1]
        ts = cur.ts
        ages = np.array([(ts - s.ts).total_seconds() for s in history])
        values = np.array([s.delay_s for s in history])
        mask10 = ages <= 600.0
        v10, t10 = values[mask10], ages[mask10]
        mask5 = t10 <= 300.0
        v5, t5 = v10[mask5], t10[mask5]

        delay_now = float(cur.delay_s)
        mean5 = float(v5.mean()) if len(v5) else delay_now
        slope5 = _slope(t5, v5)
        slope10 = _slope(t10, v10)

        route_key = (cur.route_id, cur.direction_id)
        length = self._route_length(cur.route_id, cur.direction_id)
        prev_trip = self.tt.prev_trip(cur.trip_id)
        prev_delay = np.nan
        prev_gap = np.nan
        if prev_trip is not None:
            for vid, s in fleet_samples.items():
                if s.trip_id == prev_trip.trip_id:
                    prev_delay = float(s.delay_s)
                    prev_gap = float(max((ts - s.ts).total_seconds(), 0.0))
                    break
        route_hist = route_samples.get(route_key)
        if route_hist:
            ages_r = np.array([(ts - s.ts).total_seconds() for s in route_hist])
            count10 = float(np.sum(ages_r <= 600.0))
            mask_r5 = ages_r <= 300.0
            mean_route5 = float(np.mean([s.delay_s for s, m in zip(route_hist, mask_r5) if m])) if mask_r5.any() else delay_now
        else:
            count10, mean_route5 = 1.0, delay_now

        feats = {
            "delay_s": delay_now,
            "delay_mean_5m": mean5,
            "delay_slope_5m": slope5,
            "delay_slope_10m": slope10,
            "speed": float(cur.speed),
            "offset_m": float(cur.offset_m),
            "along_frac": float(cur.along_m / length) if length else 0.0,
            "next_stop_m": float(cur.next_stop_m),
            "sched_headway_s": self._sched_headway(cur.route_id, cur.direction_id),
            "prev_trip_delay_s": prev_delay,
            "prev_trip_gap_s": prev_gap,
            "count_route_10m": count10,
            "mean_delay_route_5m": mean_route5,
            "hour": float(ts.hour),
            "minute": float(ts.minute),
            "dayofweek": float(ts.weekday()),
            "route_id": str(cur.route_id),
            "direction_id": str(cur.direction_id),
        }
        return {k: feats.get(k) for k in FEATURES}


def _slope(times: np.ndarray, values: np.ndarray) -> float:
    if len(times) < 2:
        return 0.0
    mask = np.isfinite(values)
    if mask.sum() < 2:
        return 0.0
    t, v = times[mask], values[mask]
    var = float(np.var(t))
    if var < 1e-9:
        return 0.0
    cov = float(np.mean((t - t.mean()) * (v - v.mean())))
    return cov / var
