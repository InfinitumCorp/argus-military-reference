# Multi-object tracker with Kalman filtering and detector interface
# >_ARGUS™ Military Edition v0.4

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
import uuid

from argus.models import Track, Classification, Provenance, new_fingerprint
from argus.detector import Detection
from argus.kalman import KalmanTrack


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@dataclass
class TrackState:
    track_id: str
    classification: Classification
    confidence: float
    kalman: KalmanTrack
    alt_m: float
    sensors: List[str] = field(default_factory=list)
    first_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    hits: int = 1
    misses: int = 0
    is_threat: bool = False

    def age_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.last_updated).total_seconds()

    def to_track(self) -> Track:
        lat, lon = self.kalman.position
        prov = Provenance(
            fingerprint=new_fingerprint("TRK"),
            sensors=list(set(self.sensors)),
            first_seen=self.first_seen,
            last_updated=self.last_updated,
        )
        explanation = (
            f"{self.classification.value.title()} track (Kalman) maintained across "
            f"{len(set(self.sensors))} sensor(s). Hits: {self.hits}, "
            f"speed ≈ {self.kalman.velocity_mps:.1f} m/s."
        )
        return Track(
            track_id=self.track_id,
            classification=self.classification,
            confidence=min(0.99, self.confidence),
            lat=lat,
            lon=lon,
            alt_m=self.alt_m,
            velocity_mps=self.kalman.velocity_mps,
            heading_deg=self.kalman.heading_deg,
            provenance=prov,
            explanation=explanation,
            is_threat=self.is_threat,
        )


class MultiObjectTracker:
    def __init__(self, max_distance_m: float = 120.0, max_misses: int = 5, min_hits: int = 2):
        self.tracks: Dict[str, TrackState] = {}
        self.max_distance_m = max_distance_m
        self.max_misses = max_misses
        self.min_hits = min_hits

    def update(self, detections: List[Detection]) -> List[Track]:
        now = datetime.now(timezone.utc)
        matched_track_ids = set()
        for state in self.tracks.values():
            dt = (now - state.last_updated).total_seconds()
            state.kalman.predict(max(dt, 0.1))
        for det in detections:
            best_track_id, best_dist = self._find_best_match(det)
            if best_track_id is not None and best_dist <= self.max_distance_m:
                self._update_track(self.tracks[best_track_id], det, now)
                matched_track_ids.add(best_track_id)
            else:
                new_id = self._create_track(det, now)
                matched_track_ids.add(new_id)
        for tid, state in list(self.tracks.items()):
            if tid not in matched_track_ids:
                state.misses += 1
        dead = [tid for tid, s in self.tracks.items() if s.misses > self.max_misses]
        for tid in dead:
            del self.tracks[tid]
        confirmed = [state.to_track() for state in self.tracks.values() if state.hits >= self.min_hits]
        return confirmed

    def _find_best_match(self, det: Detection):
        best_id = None
        best_dist = float("inf")
        for tid, state in self.tracks.items():
            if (det.classification != "unknown" and state.classification.value != det.classification and state.classification != Classification.UNKNOWN):
                continue
            lat, lon = state.kalman.position
            dist = haversine_m(lat, lon, det.lat, det.lon)
            if dist < best_dist:
                best_dist = dist
                best_id = tid
        return best_id, best_dist

    def _update_track(self, state: TrackState, det: Detection, now: datetime):
        state.kalman.update(det.lat, det.lon)
        state.alt_m = 0.6 * det.alt_m + 0.4 * state.alt_m
        state.confidence = max(state.confidence, det.confidence)
        state.sensors.append(det.sensor)
        state.hits += 1
        state.misses = 0
        state.last_updated = now
        if det.is_potential_threat or det.spectrum_anomaly:
            state.is_threat = True
        class_map = {"person": Classification.PERSON, "vehicle": Classification.VEHICLE, "uas": Classification.UAS}
        new_class = class_map.get(det.classification)
        if new_class and state.classification == Classification.UNKNOWN:
            state.classification = new_class

    def _create_track(self, det: Detection, now: datetime) -> str:
        class_map = {"person": Classification.PERSON, "vehicle": Classification.VEHICLE, "uas": Classification.UAS, "unknown": Classification.UNKNOWN}
        classification = class_map.get(det.classification, Classification.UNKNOWN)
        state = TrackState(
            track_id=f"TRK-{uuid.uuid4().hex[:8].upper()}",
            classification=classification,
            confidence=det.confidence,
            kalman=KalmanTrack(det.lat, det.lon),
            alt_m=det.alt_m,
            sensors=[det.sensor],
            first_seen=now,
            last_updated=now,
            hits=1,
            misses=0,
            is_threat=det.is_potential_threat or det.spectrum_anomaly,
        )
        self.tracks[state.track_id] = state
        return state.track_id
