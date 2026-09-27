from __future__ import annotations

from collections import deque
from datetime import datetime

import numpy as np

from ..schemas import DelaySample, TelemetryRecord
from ..schedule.timetable import Timetable
from .geometry import RouteGeometry

_STICKY_TOLERANCE_S = 900.0
_NEXT_STOP_SCAN_M = 2000.0


class DelayEstimator:
    def __init__(self, tt: Timetable, max_offset_m: float = 150.0):
        self.tt = tt
        self.max_offset_m = max_offset_m
        self._geoms: dict[tuple[str, str], RouteGeometry] = {}
        self._stop_d: dict[tuple[str, str], np.ndarray] = {}
        self._assignment: dict[str, tuple[str, float]] = {}

    def geometry(self, route_id: str, direction_id: str) -> RouteGeometry | None:
        key = (route_id, direction_id)
        if key not in self._geoms:
            stops = self.tt.route_stops(route_id, direction_id)
            if stops is None:
                return None
            self._geoms[key] = RouteGeometry([(s.lat, s.lon) for s in stops])
            self._stop_d[key] = np.array(
                [self._geoms[key].project(s.lat, s.lon)[0] for s in stops]
            )
        return self._geoms[key]

    def planned_at(self, route_id: str, direction_id: str, trip_id: str, along_m: float) -> float | None:
        trip = self.tt.trip_by_id(trip_id)
        if trip is None:
            return None
        key = (route_id, direction_id)
        geom = self.geometry(route_id, direction_id)
        if geom is None:
            return None
        stop_d = self._stop_d[key]
        planned = np.array([s.planned_s for s in trip.stops], dtype=float)
        return float(np.interp(along_m, stop_d, planned))

    def _sec_of_day(self, ts: datetime) -> float:
        return ts.hour * 3600.0 + ts.minute * 60.0 + ts.second + ts.microsecond / 1e6

    def _unwrap(self, obs_s: float, planned_s: float) -> float:
        diff = obs_s - planned_s
        if diff > 43200:
            obs_s -= 86400.0
        elif diff < -43200:
            obs_s += 86400.0
        return obs_s

    def _assign_trip(self, rec: TelemetryRecord, along_m: float) -> str | None:
        route_id, direction_id = rec.route_id, rec.direction_id
        if route_id is None or direction_id is None:
            return None
        if rec.trip_id is not None and self.tt.trip_by_id(rec.trip_id) is not None:
            return rec.trip_id
        obs_s = self._sec_of_day(rec.ts)
        candidates = self.tt.by_route.get((route_id, direction_id), [])
        best_id, best_err = None, float("inf")
        for trip in candidates:
            planned = self.planned_at(route_id, direction_id, trip.trip_id, along_m)
            if planned is None:
                continue
            err = abs(self._unwrap(obs_s, planned) - planned)
            if err < best_err:
                best_id, best_err = trip.trip_id, err
        prev = self._assignment.get(rec.vehicle_id)
        if prev is not None:
            prev_trip_id = prev[0]
            if prev_trip_id and self.tt.trip_by_id(prev_trip_id) is not None:
                planned_prev = self.planned_at(route_id, direction_id, prev_trip_id, along_m)
                if planned_prev is not None:
                    err_prev = abs(self._unwrap(obs_s, planned_prev) - planned_prev)
                    if err_prev <= best_err + 30.0 or err_prev <= 600.0:
                        return prev_trip_id
        if best_id is not None:
            self._assignment[rec.vehicle_id] = (best_id, best_err)
        return best_id

    def update(self, rec: TelemetryRecord) -> DelaySample | None:
        if rec.route_id is None or rec.direction_id is None:
            return None
        geom = self.geometry(rec.route_id, rec.direction_id)
        if geom is None:
            return None
        along_m, offset_m = geom.project(rec.lat, rec.lon)
        if offset_m > self.max_offset_m:
            return None
        trip_id = self._assign_trip(rec, along_m)
        if trip_id is None:
            return None
        planned = self.planned_at(rec.route_id, rec.direction_id, trip_id, along_m)
        if planned is None:
            return None
        obs_s = self._unwrap(self._sec_of_day(rec.ts), planned)
        delay_s = float(obs_s - planned)
        key = (rec.route_id, rec.direction_id)
        stop_d = self._stop_d[key]
        nxt = stop_d[stop_d > along_m]
        next_stop_m = float(nxt[0] - along_m) if len(nxt) else 0.0
        return DelaySample(
            vehicle_id=rec.vehicle_id,
            ts=rec.ts,
            route_id=rec.route_id,
            direction_id=rec.direction_id,
            trip_id=trip_id,
            along_m=along_m,
            offset_m=offset_m,
            speed=rec.speed,
            delay_s=delay_s,
            next_stop_m=next_stop_m,
        )

    def match_all(self, records: list[TelemetryRecord]) -> list[DelaySample]:
        ordered = sorted(records, key=lambda r: r.ts)
        self._assignment.clear()
        out = []
        for rec in ordered:
            sample = self.update(rec)
            if sample is not None:
                out.append(sample)
        return out


class VehicleMatcherState:
    def __init__(self, window: int = 60):
        self.samples: deque[DelaySample] = deque(maxlen=window)
