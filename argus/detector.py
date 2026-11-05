# Detector interface
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from dataclasses import dataclass

@dataclass
class Detection:
    detection_id: str
    sensor: str
    lat: float
    lon: float
    alt_m: float
    velocity_mps: float
    heading_deg: float
    classification: str
    confidence: float
    spectrum_anomaly: bool = False
    is_potential_threat: bool = False
    raw: Dict[str, Any] = None

class Detector(ABC):
    @abstractmethod
    def detect(self, raw_observations: List[Dict[str, Any]]) -> List[Detection]:
        ...

class SimulatedDetector(Detector):
    def detect(self, raw_observations: List[Dict[str, Any]]) -> List[Detection]:
        detections = []
        for obs in raw_observations:
            det = Detection(
                detection_id=obs.get("detection_id", "DET-UNK"),
                sensor=obs["sensor"],
                lat=obs["lat"],
                lon=obs["lon"],
                alt_m=obs.get("alt_m", 0.0),
                velocity_mps=obs.get("velocity_mps", 0.0),
                heading_deg=obs.get("heading_deg", 0.0),
                classification=obs.get("raw_class", "unknown"),
                confidence=obs.get("confidence", 0.5),
                spectrum_anomaly=obs.get("spectrum_anomaly", False),
                is_potential_threat=obs.get("is_potential_threat", False),
                raw=obs,
            )
            detections.append(det)
        return detections
