from __future__ import annotations

from collections import deque

from ..schemas import TelemetryRecord


class FleetBuffer:
    def __init__(self, maxlen: int = 240):
        self.maxlen = maxlen
        self._data: dict[str, deque[TelemetryRecord]] = {}

    def add(self, rec: TelemetryRecord) -> None:
        dq = self._data.get(rec.vehicle_id)
        if dq is None:
            dq = deque(maxlen=self.maxlen)
            self._data[rec.vehicle_id] = dq
        dq.append(rec)

    def extend(self, records) -> None:
        for rec in records:
            self.add(rec)

    def history(self, vehicle_id: str) -> deque[TelemetryRecord]:
        return self._data.get(vehicle_id, deque())

    def vehicles(self) -> list[str]:
        return list(self._data.keys())

    def last(self, vehicle_id: str) -> TelemetryRecord | None:
        dq = self._data.get(vehicle_id)
        return dq[-1] if dq else None
