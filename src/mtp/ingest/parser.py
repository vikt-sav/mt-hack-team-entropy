from __future__ import annotations

import json
import struct
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ..schemas import TelemetryRecord

_CANONICAL = (
    "vehicle_id",
    "ts",
    "lat",
    "lon",
    "speed",
    "heading",
    "route_id",
    "direction_id",
    "trip_id",
)


class NDTPParser:
    def __init__(self, mapping_path: Path | str):
        cfg = yaml.safe_load(Path(mapping_path).read_text(encoding="utf-8"))
        self.mode = cfg.get("mode", "json")
        self.fields: dict = cfg.get("fields", {})
        self.ts_format = cfg.get("json_timestamp", "epoch_s")
        self.binary_struct = struct.Struct(cfg.get("binary_struct", "!QddffffH"))
        self.binary_index_map: dict = cfg.get("binary_index_map", {})

    def parse(self, payload: bytes) -> list[TelemetryRecord]:
        if self.mode == "binary":
            return self._parse_binary(payload)
        return self._parse_json(payload)

    def _parse_json(self, payload: bytes) -> list[TelemetryRecord]:
        out: list[TelemetryRecord] = []
        for line in payload.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            rec = self._from_obj(obj)
            if rec is not None:
                out.append(rec)
        return out

    def _parse_binary(self, payload: bytes) -> list[TelemetryRecord]:
        size = self.binary_struct.size
        out: list[TelemetryRecord] = []
        for off in range(0, len(payload) - size + 1, size):
            values = self.binary_struct.unpack_from(payload, off)
            obj = {f"v{i}": v for i, v in enumerate(values)}
            rec = self._from_obj(obj)
            if rec is not None:
                out.append(rec)
        return out

    def _parse_ts(self, raw):
        if self.ts_format == "epoch_ms":
            return datetime.fromtimestamp(float(raw) / 1000.0, tz=timezone.utc)
        if self.ts_format == "iso":
            return datetime.fromisoformat(str(raw)).replace(tzinfo=timezone.utc)
        return datetime.fromtimestamp(float(raw), tz=timezone.utc)

    def _from_obj(self, obj: dict) -> TelemetryRecord | None:
        vals = {}
        for name in _CANONICAL:
            key = self.fields.get(name, name)
            if self.mode == "binary":
                idx = self.binary_index_map.get(name)
                if idx is None:
                    if name in ("speed", "heading"):
                        vals[name] = 0.0
                    continue
                vals[name] = obj.get(f"v{idx}")
            else:
                vals[name] = obj.get(key)
        if vals.get("vehicle_id") is None or vals.get("ts") is None:
            return None
        try:
            ts = self._parse_ts(vals["ts"])
            lat = float(vals["lat"])
            lon = float(vals["lon"])
        except (TypeError, ValueError):
            return None
        speed = float(vals.get("speed") or 0.0)
        heading = float(vals.get("heading") or 0.0)
        route_id = vals.get("route_id")
        direction_id = vals.get("direction_id")
        trip_id = vals.get("trip_id")
        extras = {
            k: v
            for k, v in obj.items()
            if k not in set(self.fields.values()) and not k.startswith("v")
        }
        return TelemetryRecord(
            vehicle_id=str(vals["vehicle_id"]),
            ts=ts,
            lat=lat,
            lon=lon,
            speed=speed,
            heading=heading,
            route_id=str(route_id) if route_id is not None else None,
            direction_id=str(direction_id) if direction_id is not None else None,
            trip_id=str(trip_id) if trip_id is not None else None,
            extras=extras,
        )
