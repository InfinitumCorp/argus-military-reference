"""Saved program settings.

The cyber geo-routing switch defaults to off. Precedence for one process is
the command flag, then INFINITUM_GEO_ENABLED, then the saved file, then off.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_ON = {"1", "true", "yes", "on"}
_OFF = {"0", "false", "no", "off"}
_SESSION: bool | None = None


def settings_path() -> Path:
    override = os.environ.get("ARGUS_SETTINGS_PATH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1] / "argus_settings.json"


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in _ON:
        return True
    return False


def load_settings() -> dict:
    path = settings_path()
    if not path.is_file():
        return {"geo_routing": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"settings file is not valid JSON: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"settings file must be a JSON object: {path}")
    data["geo_routing"] = _as_bool(data.get("geo_routing", False))
    return data


def save_settings(data: dict) -> None:
    payload = dict(data)
    payload["geo_routing"] = _as_bool(payload.get("geo_routing", False))
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def set_session_geo_routing(enabled: bool | None) -> None:
    global _SESSION
    _SESSION = enabled


def reset_geo_routing_state() -> None:
    set_session_geo_routing(None)


def persist_geo_routing(enabled: bool) -> None:
    data = load_settings()
    data["geo_routing"] = bool(enabled)
    save_settings(data)
    set_session_geo_routing(bool(enabled))


def geo_routing_enabled() -> bool:
    if _SESSION is not None:
        return _SESSION
    raw = os.environ.get("INFINITUM_GEO_ENABLED")
    if raw is not None and raw.strip() != "":
        token = raw.strip().lower()
        if token in _ON:
            return True
        if token in _OFF:
            return False
        raise ValueError("INFINITUM_GEO_ENABLED must be on or off")
    return _as_bool(load_settings().get("geo_routing", False))
