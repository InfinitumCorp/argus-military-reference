# Private Firmament provenance
from datetime import datetime, timezone
from typing import List, Dict, Any
from argus.models import new_fingerprint

class FirmamentRecorder:
    def __init__(self):
        self.records: List[Dict[str, Any]] = []

    def record_track(self, track_dict: Dict[str, Any]) -> str:
        rec = {"type": "track", "fingerprint": track_dict["provenance"]["fingerprint"], "track_id": track_dict["track_id"], "sensors": track_dict["provenance"]["sensors"], "recorded_at": datetime.now(timezone.utc).isoformat(), "ledger": "private_firmament"}
        self.records.append(rec)
        return rec["fingerprint"]

    def record_alert(self, alert_dict: Dict[str, Any]) -> str:
        rec = {"type": "defense_alert", "fingerprint": alert_dict["provenance"]["fingerprint"], "alert_id": alert_dict["alert_id"], "threat_type": alert_dict["threat_type"], "recorded_at": datetime.now(timezone.utc).isoformat(), "ledger": "private_firmament"}
        self.records.append(rec)
        return rec["fingerprint"]

    def record_batch(self, picture: Dict[str, Any]) -> List[str]:
        fps = []
        for t in picture.get("tracks", []): fps.append(self.record_track(t))
        for a in picture.get("defense_alerts", []): fps.append(self.record_alert(a))
        return fps

    def export(self) -> List[Dict[str, Any]]:
        return list(self.records)
