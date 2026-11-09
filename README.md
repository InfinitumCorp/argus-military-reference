# >_ARGUS™ Military Edition
# Reference Implementation v0.6

**Military use only.** Human-commanded. Edge-first. Private Firmament provenance.

## What’s new in v0.6

- **Streaming / sequential processing** (`streaming.py`)
- **Common Operating Picture visualization** (`cop.py`) — clean white Infinitum product aesthetic

## Usage

```bash
python main.py
python main.py datasets/sample_observations.csv
```

Open `cop.html` in a browser after running.

## Cyber geo data (opt-in)

Optional v2fly `geoip.dat` and `geosite.dat` annotation for observation fields
`source_ip` and `domain`. The binaries are not in git.

```bash
python3 scripts/fetch_geo.py
INFINITUM_GEO_ENABLED=1 python3 main.py
```

`INFINITUM_GEO_ENABLED` defaults off. Tracks, alerts, and recommendations stay
as they are. Attribution is in `THIRD_PARTY_NOTICES`.

All defensive recommendations remain advisory.
Mission data stays on the private Firmament path.

## Labyrinth client artifacts

Optional, explicit CID-authenticated artifact transport: [integration contract](LABYRINTH.md).
No exercise records are exported automatically.
