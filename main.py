#!/usr/bin/env python3
"""
>_ARGUS™ Military Edition — Full build demo (v0.6)
Sequential processing + Common Operating Picture visualization

Run:
  python main.py
  python main.py datasets/sample_observations.csv
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from argus.fusion import ArgusFusionEngine
from argus.edge_store import EdgeStore
from argus.firmament import FirmamentRecorder
from argus.query import SceneQuery
from argus.detector import SimulatedDetector
from argus.dataset import load_dataset
from argus.streaming import StreamingProcessor
from argus.cop import generate_cop_html
from argus.settings import geo_routing_enabled, load_settings, persist_geo_routing
from sim.feeds import generate_coherent_scenario


def split_into_batches(observations, batch_size=4):
    for i in range(0, len(observations), batch_size):
        yield observations[i:i + batch_size]


def run_pipeline(raw_observations, source_name: str):
    print("=" * 76)
    print(">_ARGUS™  ·  Military Edition  ·  ODIN° Observe Layer  ·  v0.6")
    print(f"Source: {source_name}")
    print("Streaming + Kalman + COP Visualization + Full Stack")
    print("=" * 76)
    print()
    print(f"Total observations: {len(raw_observations)}")
    processor = StreamingProcessor()
    pictures = list(processor.process_stream(split_into_batches(raw_observations, batch_size=5)))
    final_picture = pictures[-1] if pictures else {}
    print(f"Processed {len(pictures)} time steps")
    print(f"Final picture — Tracks: {final_picture.get('track_count', 0)}  Alerts: {final_picture.get('alert_count', 0)}")
    status = geo_status_line(final_picture)
    if status:
        print(status)
    print()
    if final_picture.get("tracks"):
        print("Final Kalman tracks:")
        for t in final_picture["tracks"]:
            sensors = ", ".join(t["provenance"]["sensors"])
            print(f"  {t['track_id']}  {t['classification'].upper():<10}  {t['velocity_mps']:.1f} m/s")
            print(f"    Sensors: {sensors}")
        print()
    store = EdgeStore(store_dir="edge_store")
    store.save_picture(final_picture)
    recorder = FirmamentRecorder()
    recorder.record_batch(final_picture)
    store.save_provenance(recorder.export())
    store.simulate_mesh_sync()
    cop_path = generate_cop_html(final_picture, "cop.html")
    print(f"Common Operating Picture written to: {cop_path}")
    print("Open cop.html in a browser to view the map.")
    print()
    q = SceneQuery()
    result = q.ask("What UAS are in the picture?", final_picture)
    print(f"Query: {result['answer']}")
    print()
    print("v0.6 complete. Streaming processing and COP visualization active.")
    print("All recommendations remain advisory.")
    print("=" * 76)
    out_path = Path(__file__).parent / "argus_picture.json"
    with open(out_path, "w") as f:
        json.dump(final_picture, f, indent=2)


def geo_status_line(picture: dict) -> str | None:
    geo = picture.get("geo")
    if not geo:
        return None
    count = len(geo.get("matches") or [])
    return f"Cyber geo routing: on · {count} annotated observation(s)."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=">_ARGUS™ Military Edition")
    parser.add_argument("dataset", nargs="?", help="CSV or JSONL observations")
    parser.add_argument(
        "--geo-routing",
        choices=("on", "off"),
        help="Persist the cyber geo-routing switch (default off)",
    )
    parser.add_argument(
        "--show-settings",
        action="store_true",
        help="Print the geo-routing switch and exit",
    )
    return parser


def print_geo_routing() -> None:
    saved = "on" if load_settings().get("geo_routing", False) else "off"
    effective = "on" if geo_routing_enabled() else "off"
    print(f"geo-routing: {effective}")
    print(f"saved: {saved}")


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.geo_routing is not None:
        persist_geo_routing(args.geo_routing == "on")
    if args.show_settings or args.geo_routing is not None:
        print_geo_routing()
    if args.show_settings:
        return
    if args.dataset:
        raw = load_dataset(args.dataset)
        run_pipeline(raw, args.dataset)
    else:
        raw = generate_coherent_scenario(num_objects=6, observations_per_object=4)
        run_pipeline(raw, "simulated multi-step scenario")


if __name__ == "__main__":
    main()
