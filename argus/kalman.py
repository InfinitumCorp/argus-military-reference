# Constant-velocity Kalman filter. State is [lat_deg, lon_deg, v_lat_deg_s, v_lon_deg_s].
import math
from typing import Tuple


class KalmanTrack:
    def __init__(self, lat: float, lon: float, process_noise: float = 1e-8, measurement_noise: float = 1e-6):
        self.x = [lat, lon, 0.0, 0.0]
        # Diagonal covariance: position, position, velocity, velocity.
        self.P = [1e-4, 1e-4, 1e-8, 1e-8]
        self.q = process_noise
        self.r = measurement_noise
        self._dt = 1.0

    def predict(self, dt: float):
        if dt <= 0:
            return
        self._dt = dt
        self.x[0] += self.x[2] * dt
        self.x[1] += self.x[3] * dt
        dt2 = dt * dt
        self.P[0] += self.P[2] * dt2 + self.q * dt
        self.P[1] += self.P[3] * dt2 + self.q * dt
        self.P[2] += self.q * dt
        self.P[3] += self.q * dt

    def update(self, lat: float, lon: float):
        dt = self._dt if self._dt > 0 else 1.0
        k_lat = self.P[0] / (self.P[0] + self.r)
        k_lon = self.P[1] / (self.P[1] + self.r)
        innov_lat = lat - self.x[0]
        innov_lon = lon - self.x[1]
        self.x[0] += k_lat * innov_lat
        self.x[1] += k_lon * innov_lon
        # A position residual over the predict interval is a velocity measurement.
        r_v = self.r / (dt * dt)
        k_vlat = self.P[2] / (self.P[2] + r_v)
        k_vlon = self.P[3] / (self.P[3] + r_v)
        self.x[2] += k_vlat * (innov_lat / dt)
        self.x[3] += k_vlon * (innov_lon / dt)
        self.P[0] *= (1 - k_lat)
        self.P[1] *= (1 - k_lon)
        self.P[2] *= (1 - k_vlat)
        self.P[3] *= (1 - k_vlon)

    @property
    def position(self) -> Tuple[float, float]:
        return self.x[0], self.x[1]

    @property
    def velocity_mps(self) -> float:
        v_north = self.x[2] * 111320
        v_east = self.x[3] * 111320 * math.cos(math.radians(self.x[0]))
        return math.hypot(v_north, v_east)

    @property
    def heading_deg(self) -> float:
        v_north = self.x[2] * 111320
        v_east = self.x[3] * 111320 * math.cos(math.radians(self.x[0]))
        return math.degrees(math.atan2(v_east, v_north)) % 360
