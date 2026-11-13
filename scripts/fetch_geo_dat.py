#!/usr/bin/env python3
"""Download pinned v2fly geoip.dat and geosite.dat into data/geo/.

The binaries are gitignored. Checksum mismatch stops the script and leaves
any previously verified files in place.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from argus.geo_fetch import main


if __name__ == "__main__":
    raise SystemExit(main())
