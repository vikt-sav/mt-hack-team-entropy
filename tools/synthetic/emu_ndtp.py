from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mtp.schedule.adapter import load_timetable


def _bearing(lat1, lon1, lat2, lon2) -> float:
    dlon = lon2 - lon1
    y = math.sin(math.radians(dlon)) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(math.radians(dlon))
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


class Vehicle:
    def __init__(self, vid: str, route_id: str, direction_id: str, trip_id: str, stops, rng: random.Random):
        self.vid = vid
        self.route_id = route_id
        self.direction_id = direction_id
        self.trip_id = trip_id
        self.stops = stops
        self.start_s = stops[0].planned_s
        self.end_s = stops[-1].planned_s

        cum = [0.0]
        speeds = []
        bearings = []
        for a, b in zip(stops, stops[1:]):
            dist_m = max(
                math.hypot(
                    (b.lat - a.lat) * 111_132.0,
                    (b.lon - a.lon) * 111_320.0 * math.cos(math.radians(a.lat)),
                ),
                1.0,
            )
            duration = max(b.planned_s - a.planned_s, 1.0)
            cum.append(cum[-1] + dist_m)
            speeds.append(dist_m / duration)
            bearings.append(_bearing(a.lat, a.lon, b.lat, b.lon))
        self.cum = np.array(cum)
        self.seg_speed = np.array(speeds)
        self.seg_bearing = bearings
        self.total = float(cum[-1])
        self.planned_s = np.array([s.planned_s for s in stops])
        self.rng = rng
        self.along = 0.0
        self.incidents = self._plan_incidents()

    def _plan_incidents(self) -> list[tuple[float, float, float]]:
        rng = self.rng
        span = max(self.end_s - self.start_s, 1.0)
        if rng.random() > 0.65:
            return []
        out = []
        for _ in range(rng.choices([1, 2], weights=[0.7, 0.3])[0]):
            t0 = self.start_s + rng.uniform(0.1, 0.75) * span
            dur = rng.uniform(240.0, 700.0)
            factor = rng.uniform(0.15, 0.5)
            out.append((t0, dur, factor))
        return out

    def factor_at(self, t: float) -> float:
        for t0, dur, f in self.incidents:
            if t0 <= t <= t0 + dur:
                return f
        return 1.0

    def planned_time_at(self, along: float) -> float:
        return float(np.interp(along, self.cum, self.planned_s))

    def step(self, t: float, dt: float) -> tuple[float, float, float, float] | None:
        if t < self.start_s or self.along >= self.total:
            return None
        seg = int(np.searchsorted(self.cum, self.along, side="right") - 1)
        seg = min(max(seg, 0), len(self.seg_speed) - 1)
        factor = self.factor_at(t)
        speed = self.seg_speed[seg] * factor * max(self.rng.gauss(1.0, 0.04), 0.1)
        self.along = min(self.along + speed * dt, self.total)
        dist_seg = self.cum[seg + 1] - self.cum[seg]
        frac = (self.along - self.cum[seg]) / max(dist_seg, 1e-6)
        a, b = self.stops[seg], self.stops[seg + 1]
        lat = a.lat + (b.lat - a.lat) * frac
        lon = a.lon + (b.lon - a.lon) * frac
        delay = self.planned_time_at(self.along) - t
        speed_kmh = speed * 3.6
        return lat, lon, speed_kmh, self.seg_bearing[seg], delay


def build_vehicles(tt, seed: int = 11) -> list[Vehicle]:
    rng = random.Random(seed)
    return [
        Vehicle(f"veh_{trip.trip_id}", trip.route_id, trip.direction_id, trip.trip_id, trip.stops, rng)
        for trip in tt.trips
    ]


async def run_emulator(args) -> None:
    tt = load_timetable(args.schedule)
    vehicles = build_vehicles(tt, seed=args.seed)
    day_start = datetime.combine(datetime.now(tz=timezone.utc).date(), datetime.min.time()).replace(tzinfo=timezone.utc)
    start_s = min(v.start_s for v in vehicles)
    end_s = max(v.end_s for v in vehicles)
    rng = random.Random(args.seed + 1)

    sock = None
    out_f = None
    if args.out:
        out_f = open(args.out, "w", encoding="utf-8")
    else:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print(f"[emu] vehicles: {len(vehicles)}, sim {start_s:.0f}s..{end_s:.0f}s, tick {args.tick_s}s, speed x{args.speed}")

    t = start_s
    while t <= end_s:
        ts = day_start + timedelta(seconds=t)
        epoch = ts.timestamp()
        emitted = 0
        for v in vehicles:
            state = v.step(t, args.tick_s)
            if state is None:
                continue
            lat, lon, speed, heading, delay = state
            lat += rng.gauss(0, 0.00003)
            lon += rng.gauss(0, 0.00003)
            obj = {
                "id": v.vid,
                "time": epoch,
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "speed": round(max(speed + rng.gauss(0, 2.0), 0.0), 1),
                "heading": round(heading, 1),
                "route": v.route_id,
                "dir": v.direction_id,
                "trip": v.trip_id,
                "delay_s": round(delay, 1),
            }
            line = (json.dumps(obj) + "\n").encode("utf-8")
            if out_f:
                out_f.write(line.decode("utf-8"))
            else:
                sock.sendto(line, (args.host, args.port))
            emitted += 1
        t += args.tick_s
        await asyncio.sleep(args.tick_s / args.speed)
        if args.duration and t - start_s > args.duration:
            break

    if out_f:
        out_f.close()
    else:
        sock.close()
    print("[emu] finished")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--schedule", default="data/schedules/schedule.csv")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=20660)
    ap.add_argument("--tick-s", type=float, default=10.0)
    ap.add_argument("--speed", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", default=None, help="write jsonl to file instead of udp")
    ap.add_argument("--duration", type=float, default=None, help="limit simulated seconds")
    args = ap.parse_args()
    asyncio.run(run_emulator(args))


if __name__ == "__main__":
    main()
