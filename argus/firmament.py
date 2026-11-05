# Private Firmament provenance. Records form a hash chain; they are not signed.
import hashlib
import json
from datetime import datetime, timezone
from typing import List, Dict, Any

GENESIS = "0" * 64


def _digest(prev: str, rec: Dict[str, Any]) -> str:
    body = {
        "type": rec["type"],
        "fingerprint": rec["fingerprint"],
        "recorded_at": rec["recorded_at"],
        "subject": rec.get("track_id") or rec.get("alert_id"),
        "prev": prev,
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class FirmamentRecorder:
    def __init__(self):
        self.records: List[Dict[str, Any]] = []
        self._prev = GENESIS

    def _append(self, rec: Dict[str, Any]) -> str:
        rec["prev_hash"] = self._prev
        rec["hash"] = _digest(self._prev, rec)
        self._prev = rec["hash"]
        self.records.append(rec)
        return rec["fingerprint"]

    def record_track(self, track_dict: Dict[str, Any]) -> str:
        rec = {
            "type": "track",
            "fingerprint": track_dict["provenance"]["fingerprint"],
            "track_id": track_dict["track_id"],
            "sensors": track_dict["provenance"]["sensors"],
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "ledger": "private_firmament",
        }
        return self._append(rec)

    def record_alert(self, alert_dict: Dict[str, Any]) -> str:
        rec = {
            "type": "defense_alert",
            "fingerprint": alert_dict["provenance"]["fingerprint"],
            "alert_id": alert_dict["alert_id"],
            "threat_type": alert_dict["threat_type"],
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "ledger": "private_firmament",
        }
        return self._append(rec)

    def record_batch(self, picture: Dict[str, Any]) -> List[str]:
        fps = []
        for track in picture.get("tracks", []):
            fps.append(self.record_track(track))
        for alert in picture.get("defense_alerts", []):
            fps.append(self.record_alert(alert))
        return fps

    def verify(self) -> bool:
        prev = GENESIS
        for rec in self.records:
            if rec.get("prev_hash") != prev:
                return False
            if rec.get("hash") != _digest(prev, rec):
                return False
            prev = rec["hash"]
        return True

    def export(self) -> List[Dict[str, Any]]:
        return list(self.records)
