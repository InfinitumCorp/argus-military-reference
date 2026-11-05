# Dataset loaders
import csv, json
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

class DatasetLoader:
    def load(self, path: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

class CSVObservationLoader(DatasetLoader):
    def load(self, path: str) -> List[Dict[str, Any]]:
        observations = []
        with open(path, newline="", encoding="utf-8") as f:
            for i, row in enumerate(csv.DictReader(f)):
                obs = {
                    "detection_id": row.get("detection_id", f"CSV-{i:05d}"),
                    "sensor": row.get("sensor", "UNKNOWN"),
                    "timestamp": row.get("timestamp", datetime.utcnow().isoformat()),
                    "lat": float(row.get("lat", 0)), "lon": float(row.get("lon", 0)),
                    "alt_m": float(row.get("alt_m", 0)), "velocity_mps": float(row.get("velocity_mps", 0)),
                    "heading_deg": float(row.get("heading_deg", 0)),
                    "raw_class": row.get("raw_class", row.get("class", "unknown")),
                    "confidence": float(row.get("confidence", 0.7)),
                    "spectrum_anomaly": str(row.get("spectrum_anomaly", "false")).lower() in ("true", "1", "yes"),
                    "is_potential_threat": str(row.get("is_potential_threat", "false")).lower() in ("true", "1", "yes"),
                }
                observations.append(obs)
        return observations

class JSONLinesLoader(DatasetLoader):
    def load(self, path: str) -> List[Dict[str, Any]]:
        observations = []
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if line.strip():
                    obj = json.loads(line)
                    obj.setdefault("detection_id", f"JSONL-{i:05d}")
                    observations.append(obj)
        return observations

def load_dataset(path: str) -> List[Dict[str, Any]]:
    p = Path(path)
    if p.suffix.lower() == ".csv": return CSVObservationLoader().load(path)
    if p.suffix.lower() == ".jsonl": return JSONLinesLoader().load(path)
    raise ValueError(f"Unsupported format: {p.suffix}")
