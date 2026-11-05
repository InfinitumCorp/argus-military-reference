# Edge-local store with delayed mesh sync
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any

class EdgeStore:
    def __init__(self, store_dir: str = "edge_store"):
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.pending_sync: List[Dict[str, Any]] = []

    def save_picture(self, picture: Dict[str, Any]) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.store_dir / f"picture_{ts}.json"
        with open(path, "w") as f: json.dump(picture, f, indent=2)
        self.pending_sync.append({"type": "picture", "path": str(path), "timestamp": ts})
        return str(path)

    def save_provenance(self, records: List[Dict[str, Any]]) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.store_dir / f"provenance_{ts}.json"
        payload = {"recorded_at": datetime.now(timezone.utc).isoformat(), "ledger": "private_firmament", "records": records}
        with open(path, "w") as f: json.dump(payload, f, indent=2)
        self.pending_sync.append({"type": "provenance", "path": str(path), "timestamp": ts})
        return str(path)

    def pending_count(self) -> int:
        return len(self.pending_sync)

    def simulate_mesh_sync(self) -> Dict[str, Any]:
        synced = len(self.pending_sync)
        self.pending_sync.clear()
        return {"status": "synced", "items_synced": synced, "via": "ÆTHER mesh", "timestamp": datetime.now(timezone.utc).isoformat()}
