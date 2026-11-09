#!/usr/bin/env python3
"""Fetch pinned v2fly geoip.dat and geosite.dat into the gitignored data directory."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from argus.geofetch import main

if __name__ == "__main__":
    raise SystemExit(main())
