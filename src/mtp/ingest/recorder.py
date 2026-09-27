from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ..schemas import TelemetryRecord

_SCHEMA = pa.schema(
    [
        ("vehicle_id", pa.string()),
        ("ts", pa.timestamp("us", tz="UTC")),
        ("lat", pa.float64()),
        ("lon", pa.float64()),
        ("speed", pa.float32()),
        ("heading", pa.float32()),
        ("route_id", pa.string()),
        ("direction_id", pa.string()),
        ("trip_id", pa.string()),
    ]
)


class Recorder:
    def __init__(self, root: Path | str, max_rows: int = 20000, max_seconds: float = 30.0):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_rows = max_rows
        self.max_seconds = max_seconds
        self._rows: list[dict] = []
        self._opened_at = datetime.now(tz=timezone.utc)
        self.files_written = 0

    def add(self, rec: TelemetryRecord) -> None:
        self._rows.append(
            {
                "vehicle_id": rec.vehicle_id,
                "ts": rec.ts,
                "lat": rec.lat,
                "lon": rec.lon,
                "speed": rec.speed,
                "heading": rec.heading,
                "route_id": rec.route_id,
                "direction_id": rec.direction_id,
                "trip_id": rec.trip_id,
            }
        )

    def flush_if_needed(self) -> None:
        now = datetime.now(tz=timezone.utc)
        if self._rows and (
            len(self._rows) >= self.max_rows
            or (now - self._opened_at).total_seconds() >= self.max_seconds
        ):
            self.flush()

    def flush(self) -> None:
        if not self._rows:
            return
        table = pa.Table.from_pylist(self._rows, schema=_SCHEMA)
        name = f"stream_{self._opened_at:%Y%m%d_%H%M%S}.parquet"
        pq.write_table(table, self.root / name)
        self.files_written += 1
        self._rows = []
        self._opened_at = now
