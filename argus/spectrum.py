# Spectrum / EW awareness fusion
from dataclasses import dataclass
from typing import List
from datetime import datetime, timezone

@dataclass
class SpectrumObservation:
    sensor: str
    timestamp: datetime
    lat: float
    lon: float
    interference_detected: bool
    jam_confidence: float
    frequency_band: str = "unknown"

class SpectrumFusion:
    def __init__(self):
        self.observations: List[SpectrumObservation] = []

    def ingest(self, detections: list) -> List[SpectrumObservation]:
        self.observations.clear()
        now = datetime.now(timezone.utc)
        for det in detections:
            if det.get("spectrum_anomaly"):
                obs = SpectrumObservation(
                    sensor=det["sensor"], timestamp=now, lat=det["lat"], lon=det["lon"],
                    interference_detected=True, jam_confidence=det.get("confidence", 0.7),
                    frequency_band="multi" if "EON" in det["sensor"] else "unknown",
                )
                self.observations.append(obs)
        return self.observations

    def summary(self) -> dict:
        if not self.observations:
            return {"interference_events": 0, "status": "clear"}
        return {
            "interference_events": len(self.observations),
            "status": "interference_detected",
            "highest_confidence": max(o.jam_confidence for o in self.observations),
            "sensors": list({o.sensor for o in self.observations}),
        }
