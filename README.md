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

## Cyber geo routing

Off by default. Picture output stays the same while the switch is off.
`geoip.dat` and `geosite.dat` are downloaded from pinned v2fly releases into
`data/geo/` and are not committed.

```bash
python3 scripts/fetch_geo_dat.py
python3 main.py --geo-routing on
python3 main.py --show-settings
```

`INFINITUM_GEO_ENABLED=on` or `off` overrides the saved switch for that process.
The saved switch is `argus_settings.json` (`geo_routing`).

All defensive recommendations remain advisory.
Mission data stays on the private Firmament path.

## Labyrinth client artifacts

Optional, explicit CID-authenticated artifact transport: [integration contract](LABYRINTH.md).
No exercise records are exported automatically.
