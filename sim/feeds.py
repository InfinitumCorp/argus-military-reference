# Simulated coherent multi-sensor feeds
import random
from datetime import datetime, timezone
from typing import List, Dict, Any

def generate_coherent_scenario(num_objects: int = 5, observations_per_object: int = 3) -> List[Dict[str, Any]]:
    base_lat, base_lon = 38.9072, -77.0369
    sensors_pool = ["POLLEN-SWARM-01", "NEMESIS-FPV-03", "ORBIS-INDOOR-02", "DAEMON-WARDEN-01", "EON-WEARABLE-07", "HRVST-FIELD-04", "CAMERA-NORTH-GATE"]
    detections = []
    now = datetime.now(timezone.utc)
    det_counter = 0
    for obj_idx in range(num_objects):
        true_lat = base_lat + random.uniform(-0.015, 0.015)
        true_lon = base_lon + random.uniform(-0.015, 0.015)
        true_class = random.choice(["person", "vehicle", "uas", "uas", "unknown"])
        is_threat = true_class == "uas" or random.random() < 0.2
        observers = random.sample(sensors_pool, k=min(observations_per_object, len(sensors_pool)))
        for sensor in observers:
            noise_lat = random.uniform(-0.0003, 0.0003)
            noise_lon = random.uniform(-0.0003, 0.0003)
            det = {
                "detection_id": f"DET-{det_counter:04d}",
                "sensor": sensor,
                "timestamp": now.isoformat(),
                "lat": true_lat + noise_lat,
                "lon": true_lon + noise_lon,
                "alt_m": random.uniform(10, 120) if true_class == "uas" else random.uniform(0, 20),
                "velocity_mps": random.uniform(0, 18),
                "heading_deg": random.uniform(0, 360),
                "raw_class": true_class,
                "confidence": random.uniform(0.65, 0.97),
                "spectrum_anomaly": is_threat and random.random() < 0.4,
                "is_potential_threat": is_threat,
            }
            detections.append(det)
            det_counter += 1
    random.shuffle(detections)
    return detections
