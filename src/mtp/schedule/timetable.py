from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Stop:
    seq: int
    stop_id: str
    name: str
    lat: float
    lon: float
    planned_s: float


@dataclass
class Trip:
    trip_id: str
    route_id: str
    direction_id: str
    stops: list[Stop]

    @property
    def start_s(self) -> float:
        return self.stops[0].planned_s


class Timetable:
    def __init__(self, trips: list[Trip]):
        self.trips = sorted(trips, key=lambda t: (t.route_id, t.direction_id, t.start_s, t.trip_id))
        self.by_route: dict[tuple[str, str], list[Trip]] = {}
        for trip in self.trips:
            self.by_route.setdefault((trip.route_id, trip.direction_id), []).append(trip)
        self.trip_index: dict[str, int] = {t.trip_id: i for i, t in enumerate(self.trips)}

    def routes(self) -> list[tuple[str, str]]:
        return list(self.by_route.keys())

    def trip_by_id(self, trip_id: str) -> Trip | None:
        idx = self.trip_index.get(trip_id)
        return self.trips[idx] if idx is not None else None

    def prev_trip(self, trip_id: str) -> Trip | None:
        idx = self.trip_index.get(trip_id)
        if idx is None or idx == 0:
            return None
        prev = self.trips[idx - 1]
        cur = self.trips[idx]
        if (prev.route_id, prev.direction_id) != (cur.route_id, cur.direction_id):
            return None
        return prev

    def scheduled_headway_s(self, route_id: str, direction_id: str) -> float | None:
        trips = self.by_route.get((route_id, direction_id))
        if not trips or len(trips) < 2:
            return None
        starts = np.array([t.start_s for t in trips], dtype=float)
        diffs = np.diff(np.sort(starts))
        diffs = diffs[diffs > 60]
        if len(diffs) == 0:
            return None
        return float(np.median(diffs))

    def route_stops(self, route_id: str, direction_id: str) -> list[Stop] | None:
        trips = self.by_route.get((route_id, direction_id))
        return trips[0].stops if trips else None
