from __future__ import annotations

import numpy as np
from shapely.geometry import LineString, Point


class RouteGeometry:
    def __init__(self, points: list[tuple[float, float]]):
        if len(points) < 2:
            raise ValueError("route needs at least 2 points")
        self.points = np.array(points, dtype=float)
        lat0 = float(self.points[:, 0].mean())
        lon0 = float(self.points[:, 1].mean())
        lat_m = 111_132.0
        lon_m = 111_320.0 * np.cos(np.deg2rad(lat0))
        xs = (self.points[:, 1] - lon0) * lon_m
        ys = (self.points[:, 0] - lat0) * lat_m
        self._line = LineString(zip(xs, ys))
        self._lat0 = lat0
        self._lon0 = lon0
        self._lat_m = lat_m
        self._lon_m = lon_m

    @property
    def length_m(self) -> float:
        return float(self._line.length)

    def project(self, lat: float, lon: float) -> tuple[float, float]:
        x = (lon - self._lon0) * self._lon_m
        y = (lat - self._lat0) * self._lat_m
        d = self._line.project(Point(x, y))
        offset = self._line.distance(Point(x, y))
        return float(d), float(offset)

    def interpolate(self, along_m: float) -> tuple[float, float]:
        along_m = min(max(along_m, 0.0), self.length_m)
        p = self._line.interpolate(along_m)
        lon = self._lon0 + p.x / self._lon_m
        lat = self._lat0 + p.y / self._lat_m
        return float(lat), float(lon)

    def bearing(self, along_m: float) -> float:
        along_m = min(max(along_m, 0.0), self.length_m - 1e-6)
        p1 = self._line.interpolate(along_m)
        p2 = self._line.interpolate(along_m + 1.0)
        dx = p2.x - p1.x
        dy = p2.y - p1.y
        return (np.degrees(np.arctan2(dx, dy)) + 360.0) % 360.0

    def coords_latlon(self) -> list[tuple[float, float]]:
        return [
            (self._lat0 + y / self._lat_m, self._lon0 + x / self._lon_m)
            for x, y in self._line.coords
        ]
