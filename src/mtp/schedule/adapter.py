from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from .timetable import Stop, Timetable, Trip

_TIME_FORMATS = ("%H:%M:%S", "%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


def _parse_time(raw: str) -> float:
    s = str(raw).strip()
    for fmt in _TIME_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            if fmt == _TIME_FORMATS[2] or fmt == _TIME_FORMATS[3]:
                base = dt.replace(hour=0, minute=0, second=0, microsecond=0)
                return (dt - base).total_seconds()
            return dt.hour * 3600 + dt.minute * 60 + dt.second
        except ValueError:
            continue
    return float(s)


def load_timetable(path: Path | str, columns: dict | None = None) -> Timetable:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"schedule not found: {path}")
    colmap = columns or {}
    df = pd.read_csv(path, dtype=str)
    df = df.rename(columns={v: k for k, v in colmap.items() if v in df.columns})
    required = {"route_id", "direction_id", "trip_id", "stop_seq", "lat", "lon", "arrive_time"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"schedule is missing columns: {sorted(missing)}")
    if "stop_id" not in df.columns:
        df["stop_id"] = df["route_id"] + "_" + df["stop_seq"]
    if "stop_name" not in df.columns:
        df["stop_name"] = df["stop_id"]

    trips: list[Trip] = []
    for (trip_id, route_id, direction_id), group in df.groupby(
        ["trip_id", "route_id", "direction_id"], sort=True
    ):
        group = group.copy()
        group["seq_int"] = pd.to_numeric(group["stop_seq"], errors="coerce")
        group = group.dropna(subset=["seq_int"]).sort_values("seq_int")
        stops = [
            Stop(
                seq=int(row.stop_seq),
                stop_id=str(row.stop_id),
                name=str(row.stop_name),
                lat=float(row.lat),
                lon=float(row.lon),
                planned_s=_parse_time(row.arrive_time),
            )
            for row in group.itertuples(index=False)
        ]
        if stops:
            trips.append(Trip(trip_id=str(trip_id), route_id=str(route_id), direction_id=str(direction_id), stops=stops))
    return Timetable(trips)


def write_schedule_csv(path: Path | str, trips: list[Trip]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            ["route_id", "direction_id", "trip_id", "stop_seq", "stop_id", "stop_name", "lat", "lon", "arrive_time"]
        )
        for trip in trips:
            for stop in trip.stops:
                hh = int(stop.planned_s // 3600) % 24
                mm = int((stop.planned_s % 3600) // 60)
                ss = int(stop.planned_s % 60)
                w.writerow(
                    [
                        trip.route_id,
                        trip.direction_id,
                        trip.trip_id,
                        stop.seq,
                        stop.stop_id,
                        stop.name,
                        f"{stop.lat:.6f}",
                        f"{stop.lon:.6f}",
                        f"{hh:02d}:{mm:02d}:{ss:02d}",
                    ]
                )
