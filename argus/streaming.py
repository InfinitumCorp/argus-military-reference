# Streaming / sequential processor
from typing import List, Dict, Any, Iterator
from argus.fusion import ArgusFusionEngine
from argus.detector import SimulatedDetector

class StreamingProcessor:
    def __init__(self):
        self.engine = ArgusFusionEngine(detector=SimulatedDetector())
        self.history: List[Dict[str, Any]] = []

    def process_batch(self, observations: List[Dict[str, Any]]) -> Dict[str, Any]:
        picture = self.engine.ingest_and_fuse(observations)
        self.history.append({"timestamp": picture["timestamp"], "track_count": picture["track_count"], "alert_count": picture["alert_count"]})
        return picture

    def process_stream(self, observation_batches: Iterator[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        return [self.process_batch(batch) for batch in observation_batches]
