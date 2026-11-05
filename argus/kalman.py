# Constant-velocity Kalman filter
import math
from typing import Tuple

class KalmanTrack:
    def __init__(self, lat: float, lon: float, process_noise: float = 1e-8, measurement_noise: float = 1e-6):
        self.x = [lat, lon, 0.0, 0.0]
        self.P = [1e-4, 1e-4, 1e-6, 1e-6]
        self.q = process_noise
        self.r = measurement_noise

    def predict(self, dt: float):
        if dt <= 0: return
        self.x[0] += self.x[2] * dt
        self.x[1] += self.x[3] * dt
        self.P[0] += self.q * dt
        self.P[1] += self.q * dt

    def update(self, lat: float, lon: float):
        k_lat = self.P[0] / (self.P[0] + self.r)
        k_lon = self.P[1] / (self.P[1] + self.r)
        innov_lat = lat - self.x[0]
        innov_lon = lon - self.x[1]
        self.x[0] += k_lat * innov_lat
        self.x[1] += k_lon * innov_lon
        self.x[2] = 0.7 * self.x[2] + 0.3 * (innov_lat * 0.5)
        self.x[3] = 0.7 * self.x[3] + 0.3 * (innov_lon * 0.5)
        self.P[0] *= (1 - k_lat)
        self.P[1] *= (1 - k_lon)

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
