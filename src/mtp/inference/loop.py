from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ..config import Settings
from ..features.builder import LiveFeatureBuilder
from ..ingest.buffer import FleetBuffer
from ..matching.delay import DelayEstimator
from ..schedule.timetable import Timetable
from ..schemas import DelaySample


class Predictor:
    def __init__(self, models_dir: Path | str | None):
        self.model = None
        self.q10 = None
        self.q90 = None
        if models_dir and Path(models_dir, "predictor.cbm").exists():
            from catboost import CatBoostRegressor

            self.model = CatBoostRegressor()
            self.model.load_model(str(Path(models_dir, "predictor.cbm")))
            for name, attr in (("quantile_10.cbm", "q10"), ("quantile_90.cbm", "q90")):
                p = Path(models_dir, name)
                if p.exists():
                    m = CatBoostRegressor()
                    m.load_model(str(p))
                    setattr(self, attr, m)

    def predict(self, features: dict) -> tuple[float, float | None, float | None]:
        if self.model is None:
            base = float(features["delay_s"])
            return base, None, None
        row = {k: [features[k]] for k in self.model.feature_names_}
        import pandas as pd

        x = pd.DataFrame(row)
        pred = float(self.model.predict(x)[0])
        lo = float(self.q10.predict(x)[0]) if self.q10 else None
        hi = float(self.q90.predict(x)[0]) if self.q90 else None
        return pred, lo, hi


class InferenceLoop:
    def __init__(
        self,
        settings: Settings,
        tt: Timetable,
        buffer: FleetBuffer,
        models_dir: Path | str | None = "data/models",
    ):
        self.settings = settings
        self.tt = tt
        self.buffer = buffer
        self.estimator = DelayEstimator(tt, max_offset_m=float(settings.target["max_lateral_offset_m"]))
        self.feature_builder = LiveFeatureBuilder(tt, geometry_fn=self.estimator.geometry)
        self.predictor = Predictor(models_dir)
        self.interval_s = float(settings.inference["interval_s"])
        self.active_window_s = float(settings.inference["active_window_s"])
        self._samples: dict[str, deque[DelaySample]] = {}
        self._processed: dict[str, int] = {}
        self._fleet_last: dict[str, DelaySample] = {}
        self._route_samples: dict[tuple[str, str], deque[DelaySample]] = {}
        self.snapshot: list[dict] = []
        self.snapshot_ts: str | None = None
        self.ticks = 0
        self._last_data_ts: datetime | None = None

    def _drain(self) -> list[DelaySample]:
        fresh: list[DelaySample] = []
        for vid in self.buffer.vehicles():
            history = self.buffer.history(vid)
            count = self._processed.get(vid, 0)
            if len(history) <= count:
                continue
            for rec in list(history)[count:]:
                if self._last_data_ts is None or rec.ts > self._last_data_ts:
                    self._last_data_ts = rec.ts
                sample = self.estimator.update(rec)
                if sample is not None:
                    dq = self._samples.setdefault(vid, deque(maxlen=240))
                    dq.append(sample)
                    fresh.append(sample)
            self._processed[vid] = len(history)
        return fresh

    def _register(self, fresh: list[DelaySample]) -> None:
        for s in fresh:
            key = (s.route_id, s.direction_id)
            rq = self._route_samples.setdefault(key, deque(maxlen=2000))
            rq.append(s)
        self._fleet_last = {vid: dq[-1] for vid, dq in self._samples.items() if dq}

    def tick(self) -> list[dict]:
        fresh = self._drain()
        self._register(fresh)
        now = self._last_data_ts or datetime.now(tz=timezone.utc)
        rows = []
        for vid, dq in self._samples.items():
            cur = dq[-1]
            age_s = (now - cur.ts).total_seconds()
            if age_s > self.active_window_s:
                continue
            feats = self.feature_builder.build(dq, self._fleet_last, self._route_samples)
            if feats is None:
                continue
            pred, lo, hi = self.predictor.predict(feats)
            rows.append(
                {
                    "vehicle_id": vid,
                    "lat": float(self.buffer.last(vid).lat),
                    "lon": float(self.buffer.last(vid).lon),
                    "route_id": cur.route_id,
                    "direction_id": cur.direction_id,
                    "trip_id": cur.trip_id,
                    "delay_s": round(cur.delay_s, 1),
                    "pred_s": round(pred, 1),
                    "pred_lo_s": round(lo, 1) if lo is not None else None,
                    "pred_hi_s": round(hi, 1) if hi is not None else None,
                    "horizon_s": int(self.settings.target["horizon_s"]),
                    "ts": cur.ts.isoformat(),
                }
            )
        rows.sort(key=lambda r: -abs(r["pred_s"]))
        self.snapshot = rows
        self.snapshot_ts = now.isoformat()
        self.ticks += 1
        return rows

    async def run(self) -> None:
        while True:
            try:
                self.tick()
            except Exception as exc:
                print(f"[inference] tick error: {exc}")
            await asyncio.sleep(self.interval_s)


def risk_color(pred_s: float) -> str:
    minutes = pred_s / 60.0
    if minutes >= 5:
        return "#e74c3c"
    if minutes >= 2:
        return "#e67e22"
    if minutes >= 0.5:
        return "#f1c40f"
    return "#2ecc71"
