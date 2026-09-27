from __future__ import annotations

import argparse
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mtp.schedule.adapter import write_schedule_csv
from mtp.schedule.timetable import Stop, Trip


def gen_routes(n_routes: int, stops_per_route: int, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    routes = []
    base_lat, base_lon = 55.75, 37.60
    for r in range(n_routes):
        angle = rng.uniform(0, 2 * math.pi)
        lat0 = base_lat + rng.uniform(-0.05, 0.05)
        lon0 = base_lon + rng.uniform(-0.08, 0.08)
        dx = math.cos(angle)
        dy = math.sin(angle)
        stops = []
        lat, lon = lat0, lon0
        for i in range(stops_per_route):
            stops.append((round(lat, 6), round(lon, 6)))
            step = rng.uniform(500.0, 800.0)
            lat += dy * step / 111_132.0
            lon += dx * step / (111_320.0 * math.cos(math.radians(lat0)))
        routes.append({"route_id": f"m{r + 1}", "stops": stops})
    return routes


def gen_trips(routes: list[dict], headway_s: int, start_s: int, end_s: int, cruise_mps: float = 6.0, dwell_s: float = 20.0) -> list[Trip]:
    trips: list[Trip] = []
    for route in routes:
        stops_geo = route["stops"]
        for direction_id, seq in (("1", stops_geo), ("2", list(reversed(stops_geo)))):
            seg_times = []
            t = 0.0
            for i in range(len(seq) - 1):
                (la1, lo1), (la2, lo2) = seq[i], seq[i + 1]
                dist_m = math.hypot((la2 - la1) * 111_132.0, (lo2 - lo1) * 111_320.0 * math.cos(math.radians(la1)))
                seg_times.append(dist_m / cruise_mps + dwell_s)
            total_s = sum(seg_times)
            k = 0
            t_start = start_s
            while t_start + total_s <= end_s:
                k += 1
                stops = []
                planned = float(t_start)
                for i, (la, lo) in enumerate(seq):
                    if i > 0:
                        planned += seg_times[i - 1]
                    stops.append(
                        Stop(seq=i, stop_id=f"{route['route_id']}_{direction_id}_{i}", name=f"Остановка {i}", lat=la, lon=lo, planned_s=planned)
                    )
                trips.append(
                    Trip(trip_id=f"{route['route_id']}_{direction_id}_{k:04d}", route_id=route["route_id"], direction_id=direction_id, stops=stops)
                )
                t_start += headway_s
    return trips


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/schedules/schedule.csv")
    ap.add_argument("--routes", type=int, default=6)
    ap.add_argument("--stops", type=int, default=14)
    ap.add_argument("--headway-min", type=int, default=10)
    ap.add_argument("--start", default="06:00")
    ap.add_argument("--end", default="12:00")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    h1, m1 = map(int, args.start.split(":"))
    h2, m2 = map(int, args.end.split(":"))
    start_s, end_s = h1 * 3600 + m1 * 60, h2 * 3600 + m2 * 60
    routes = gen_routes(args.routes, args.stops, seed=args.seed)
    trips = gen_trips(routes, args.headway_min * 60, start_s, end_s)
    write_schedule_csv(args.out, trips)
    print(f"[gen_schedule] {len(trips)} trips on {args.routes} routes -> {args.out}")


if __name__ == "__main__":
    main()
