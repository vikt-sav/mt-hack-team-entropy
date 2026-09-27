from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class TelemetryRecord:
    vehicle_id: str
    ts: datetime
    lat: float
    lon: float
    speed: float = 0.0
    heading: float = 0.0
    route_id: str | None = None
    direction_id: str | None = None
    trip_id: str | None = None
    extras: dict = field(default_factory=dict)


@dataclass(slots=True)
class DelaySample:
    vehicle_id: str
    ts: datetime
    route_id: str
    direction_id: str
    trip_id: str
    along_m: float
    offset_m: float
    speed: float
    delay_s: float
    next_stop_m: float
