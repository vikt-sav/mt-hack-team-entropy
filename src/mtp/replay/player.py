from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pandas as pd

from ..ingest.recorder import _SCHEMA


def rows_to_payload(row: pd.Series) -> bytes:
    obj = {
        "id": str(row["vehicle_id"]),
        "time": row["ts"].timestamp(),
        "lat": float(row["lat"]),
        "lon": float(row["lon"]),
        "speed": float(row["speed"]),
        "heading": float(row["heading"]),
        "route": None if pd.isna(row["route_id"]) else str(row["route_id"]),
        "dir": None if pd.isna(row["direction_id"]) else str(row["direction_id"]),
        "trip": None if pd.isna(row["trip_id"]) else str(row["trip_id"]),
    }
    return (json.dumps(obj) + "\n").encode("utf-8")


async def run_replay(pipeline, raw_dir: Path | str, speed: float = 60.0, loop: bool = True) -> None:
    import pyarrow.parquet as pq

    files = sorted(Path(raw_dir).glob("stream_*.parquet"))
    if not files:
        print(f"[replay] no files in {raw_dir}")
        return
    frames = [pq.read_table(f, schema=_SCHEMA).to_pandas() for f in files]
    df = pd.concat(frames, ignore_index=True).sort_values("ts")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    print(f"[replay] {len(df)} records, speed x{speed}")

    grouped = df.groupby("ts", sort=True)
    base_ts = None
    base_wall = asyncio.get_event_loop().time()
    while True:
        for ts, group in grouped:
            if base_ts is None:
                base_ts = ts
            target = base_wall + (ts - base_ts).total_seconds() / speed
            now = asyncio.get_event_loop().time()
            if target > now:
                await asyncio.sleep(target - now)
            for _, row in group.iterrows():
                pipeline.sink(rows_to_payload(row))
        if not loop:
            break
        base_ts = None
        base_wall = asyncio.get_event_loop().time()
    print("[replay] finished")
