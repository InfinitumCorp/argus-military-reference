# Fusion engine with Detector interface + Kalman tracker
from datetime import datetime, timezone
from typing import List, Dict, Any
from argus.models import DefenseAlert, ThreatType, Provenance, new_fingerprint
from argus.tracker import MultiObjectTracker
from argus.spectrum import SpectrumFusion
from argus.anticipation import AnticipationEngine
from argus.detector import Detector, SimulatedDetector
from argus.geo_policy import apply_geo_policy

class ArgusFusionEngine:
    def __init__(self, detector: Detector = None):
        self.detector = detector or SimulatedDetector()
        self.tracker = MultiObjectTracker(max_distance_m=150.0, max_misses=5, min_hits=2)
        self.spectrum = SpectrumFusion()
        self.anticipation = AnticipationEngine()
        self.alerts: List[DefenseAlert] = []

    def ingest_and_fuse(self, raw_observations: List[Dict[str, Any]]) -> Dict[str, Any]:
        self.alerts.clear()
        detections = self.detector.detect(raw_observations)
        self.spectrum.ingest(raw_observations)
        spectrum_summary = self.spectrum.summary()
        confirmed_tracks = self.tracker.update(detections)
        for track in confirmed_tracks:
            if track.is_threat or track.classification.value == "uas":
                alert = self._create_defense_alert(track)
                if alert:
                    self.alerts.append(alert)
        if spectrum_summary.get("interference_events", 0) > 0:
            self.alerts.append(self._spectrum_alert(spectrum_summary))
        self.alerts.sort(key=lambda a: a.priority, reverse=True)
        picture = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "track_count": len(confirmed_tracks),
            "alert_count": len(self.alerts),
            "tracks": [t.to_dict() for t in confirmed_tracks],
            "defense_alerts": [a.to_dict() for a in self.alerts],
            "spectrum": spectrum_summary,
            "notes": "Human-commanded. Recommendations are advisory. Private Firmament provenance.",
        }
        picture["forecasts"] = self.anticipation.forecast(picture)
        apply_geo_policy(picture, raw_observations)
        return picture

    def _create_defense_alert(self, track):
        if track.classification.value == "uas":
            ttype = ThreatType.UAS
            rec = "Persistent UAS track across sensors. Correlate with DAEMON/WARDEN. Human approval required."
        elif track.is_threat:
            ttype = ThreatType.ANOMALOUS_TRACK
            rec = "Anomalous track maintained. Continue observation. No action without commander approval."
        else:
            return None
        now = datetime.now(timezone.utc)
        prov = Provenance(fingerprint=new_fingerprint("ALT"), sensors=track.provenance.sensors, first_seen=now, last_updated=now)
        return DefenseAlert(alert_id=f"ALT-{track.track_id}", threat_type=ttype, priority=min(1.0, track.confidence * 1.1), confidence=track.confidence, linked_tracks=[track.track_id], explanation=track.explanation, recommendation=rec, provenance=prov)

    def _spectrum_alert(self, summary):
        now = datetime.now(timezone.utc)
        prov = Provenance(fingerprint=new_fingerprint("SPC"), sensors=summary.get("sensors", []), first_seen=now, last_updated=now)
        return DefenseAlert(alert_id="ALT-SPECTRUM", threat_type=ThreatType.SPECTRUM_INTERFERENCE, priority=min(1.0, summary.get("highest_confidence", 0.7)), confidence=summary.get("highest_confidence", 0.7), linked_tracks=[], explanation=f"Spectrum interference detected.", recommendation="Monitor spectrum. Advisory only.", provenance=prov)
