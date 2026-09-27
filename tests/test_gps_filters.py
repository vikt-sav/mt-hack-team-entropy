import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mtp.online import _drop_gps_jumps

LAT0, LON0 = 55.8, 37.4


def run_filter(la, lo, ts=None):
    ts = ts if ts is not None else np.arange(len(la), dtype=float) * 60.0
    return _drop_gps_jumps(ts, np.asarray(la, float), np.asarray(lo, float),
                           np.zeros(len(la)), np.zeros(len(la)), LAT0, LON0)


def test_isolated_teleport_dropped():
    r = run_filter([55.80, 55.845, 55.801], [37.40, 37.40, 37.401])
    assert len(r[0]) == 2


def test_tail_teleport_dropped():
    r = run_filter([55.80, 55.801, 55.845], [37.40, 37.401, 37.40])
    assert len(r[0]) == 2


def test_legit_track_kept():
    t = np.array([0.0, 60.0, 120.0, 180.0])
    la = 55.80 + 12.0 * t / 111_132.0
    r = run_filter(la, [37.40] * 4, ts=t)
    assert len(r[0]) == 4


def test_far_point_dropped_and_long_gap_kept():
    r = run_filter([55.80, 56.70, 55.801], [37.40, 37.40, 37.401])
    assert len(r[0]) == 2
    r = run_filter([55.80, 55.85, 55.8501], [37.40, 37.40, 37.4001], ts=np.array([0.0, 1800.0, 3600.0]))
    assert len(r[0]) == 3


def test_zero_point_dropped():
    r = run_filter([55.80, 0.0, 55.801], [37.40, 0.0, 37.401])
    assert len(r[0]) == 2
