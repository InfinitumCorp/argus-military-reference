"""Opt-in cyber geo routing annotation and log.

When the switch is off this returns without reading datasets or changing the
picture, so recommendations, tracks, and alerts stay as they were.
"""

from __future__ import annotations

import logging
from typing import Any

from argus.geo import GeoIndex, load_index
from argus.settings import geo_routing_enabled

log = logging.getLogger("argus.geo")


def _text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def endpoints(observation: dict[str, Any]) -> tuple[str, str]:
    ip = _text(observation.get("ip")) or _text(observation.get("src_ip"))
    domain = _text(observation.get("domain")) or _text(observation.get("host"))
    return ip, domain


def apply_geo_policy(
    picture: dict[str, Any],
    observations: list[dict[str, Any]],
    *,
    index: GeoIndex | None = None,
) -> None:
    if not geo_routing_enabled():
        return
    datasets = index if index is not None else load_index()
    matches = []
    seen: set[tuple[str, str]] = set()
    for observation in observations:
        ip, domain = endpoints(observation)
        if not ip and not domain:
            continue
        key = (ip, domain)
        if key in seen:
            continue
        seen.add(key)
        match = {
            "ip": ip or None,
            "country": datasets.country_for_ip(ip) if ip else None,
            "domain": domain or None,
            "categories": datasets.categories_for_domain(domain) if domain else [],
        }
        matches.append(match)
        log.debug(
            "geo %s country=%s categories=%s",
            ip or domain,
            match["country"],
            ",".join(match["categories"]),
        )
    picture["geo"] = {
        "enabled": True,
        "source": "v2fly",
        "matches": matches,
        "note": "Opt-in cyber geo routing annotation. Advisory only. Human command unchanged.",
    }
    log.info("cyber geo routing annotated %d observation(s)", len(matches))
