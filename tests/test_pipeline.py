import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mtp.ingest.parser import NDTPParser
from mtp.matching.delay import DelayEstimator
from mtp.schedule.adapter import load_timetable
from mtp.schemas import TelemetryRecord


def make_mapping(tmp_path, mode="json"):
    cfg = {
        "mode": mode,
        "json_timestamp": "epoch_s",
        "binary_struct": "!QddffffH",
        "fields": {
            "vehicle_id": "id",
            "ts": "time",
            "lat": "lat",
            "lon": "lon",
            "speed": "speed",
            "heading": "heading",
            "route_id": "route",
            "direction_id": "dir",
            "trip_id": "trip",
        },
        "binary_index_map": {
            "vehicle_id": 0,
            "ts": 1,
            "lat": 2,
            "lon": 3,
            "speed": 4,
            "heading": 5,
        },
    }
    import yaml

    p = tmp_path / "ndtp.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return p


def test_parser_json_roundtrip(tmp_path):
    parser = NDTPParser(make_mapping(tmp_path))
    payload = (
        b'{"id":"v1","time":1700000000.0,"lat":55.75,"lon":37.6,"speed":12.5,'
        b'"heading":90.0,"route":"m1","dir":"1","trip":"t1"}\n'
        b'{"id":"v2","time":1700000010.0,"lat":55.76,"lon":37.61,"speed":10.0,"heading":45.0}\n'
    )
    recs = parser.parse(payload)
    assert len(recs) == 2
    assert recs[0].vehicle_id == "v1"
    assert recs[0].route_id == "m1"
    assert recs[0].trip_id == "t1"
    assert recs[1].route_id is None


def test_parser_binary_roundtrip(tmp_path):
    parser = NDTPParser(make_mapping(tmp_path, mode="binary"))
    import struct

    payload = struct.pack("!QddffffH", 77, 1700000000.0, 55.75, 37.6, 12.0, 90.0, 0.0, 1)
    recs = parser.parse(payload)
    assert len(recs) == 1
    assert recs[0].vehicle_id == "77"
    assert abs(recs[0].lat - 55.75) < 1e-6


def make_schedule(tmp_path):
    csv = tmp_path / "schedule.csv"
    rows = [
        "route_id,direction_id,trip_id,stop_seq,stop_id,stop_name,lat,lon,arrive_time",
        "m1,1,t1,0,s0,Stop0,55.7500,37.6000,06:00:00",
        "m1,1,t1,1,s1,Stop1,55.7590,37.6000,06:10:00",
        "m1,1,t1,2,s2,Stop2,55.7680,37.6000,06:20:00",
        "m1,1,t2,0,s0,Stop0,55.7500,37.6000,06:08:00",
        "m1,1,t2,1,s1,Stop1,55.7590,37.6000,06:18:00",
        "m1,1,t2,2,s2,Stop2,55.7680,37.6000,06:28:00",
    ]
    csv.write_text("\n".join(rows), encoding="utf-8")
    return csv


def test_schedule_adapter(tmp_path):
    tt = load_timetable(make_schedule(tmp_path))
    assert len(tt.trips) == 2
    assert tt.scheduled_headway_s("m1", "1") == pytest.approx(480.0)
    assert tt.prev_trip("t2").trip_id == "t1"


def test_osm_graph_routing():
    from mtp.osm import RoadRouter

    data = {
        "elements": [
            {"type": "node", "id": 1, "lat": 55.7500, "lon": 37.6000},
            {"type": "node", "id": 2, "lat": 55.7590, "lon": 37.6000},
            {"type": "node", "id": 3, "lat": 55.7680, "lon": 37.6000},
            {"type": "node", "id": 4, "lat": 55.7590, "lon": 37.6100},
            {"type": "way", "id": 10, "nodes": [1, 2, 3]},
            {"type": "way", "id": 11, "nodes": [2, 4]},
        ]
    }
    router = RoadRouter(data)
    path = router.route_between(55.7500, 37.6000, 55.7680, 37.6000)
    assert path is not None and len(path) >= 3
    straight = ((55.7680 - 55.7500) * 111_132.0)
    on_road = sum(
        ((b[0] - a[0]) * 111_132.0) ** 2 + ((b[1] - a[1]) * 111_320.0) ** 2
        for a, b in zip(path, path[1:])
    ) ** 0.5
    assert on_road <= straight * 1.10
    far = router.route_between(55.7500, 37.6000, 56.9000, 39.0000)
    assert far is None or isinstance(far, list)


def test_matching_on_time_and_late(tmp_path):
    tt = load_timetable(make_schedule(tmp_path))
    est = DelayEstimator(tt)

    base = np.datetime64("2026-09-22T06:00:00", "ns").astype(object)
    from datetime import datetime, timezone

    t0 = datetime(2026, 9, 22, 6, 0, 0, tzinfo=timezone.utc)
    rec_on_time = TelemetryRecord(
        vehicle_id="bus1", ts=t0, lat=55.75, lon=37.6, speed=20,
        route_id="m1", direction_id="1", trip_id="t1",
    )
    s = est.update(rec_on_time)
    assert s is not None
    assert abs(s.delay_s) < 60

    est2 = DelayEstimator(tt)
    t_late = datetime(2026, 9, 22, 6, 8, 0, tzinfo=timezone.utc)
    rec_late = TelemetryRecord(
        vehicle_id="bus2", ts=t_late, lat=55.7500, lon=37.6000, speed=20,
        route_id="m1", direction_id="1", trip_id="t1",
    )
    s2 = est2.update(rec_late)
    assert s2 is not None
    assert s2.delay_s > 400
