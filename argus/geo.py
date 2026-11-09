"""v2ray GeoIPList / GeoSiteList loader.

Reads geoip.dat and geosite.dat with the standard library. Country and
category lookup uses the longest matching prefix and v2ray domain rules
(full, domain, plain, regex). Reverse-match GeoIP entries are not countries.
"""

from __future__ import annotations

import ipaddress
import os
import re
from pathlib import Path


def default_data_dir() -> Path:
    override = os.environ.get("ARGUS_GEO_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1] / "data" / "geo"


def _read_varint(buf: bytes, index: int) -> tuple[int, int]:
    shift = 0
    value = 0
    size = len(buf)
    while True:
        if index >= size:
            raise ValueError("truncated protobuf")
        byte = buf[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, index
        shift += 7
        if shift > 63:
            raise ValueError("protobuf varint too long")


def _iter_fields(buf: bytes):
    index = 0
    size = len(buf)
    while index < size:
        key, index = _read_varint(buf, index)
        field, wire = key >> 3, key & 7
        if field == 0:
            raise ValueError("invalid protobuf field")
        if wire == 0:
            value, index = _read_varint(buf, index)
        elif wire == 2:
            length, index = _read_varint(buf, index)
            end = index + length
            if length < 0 or end > size:
                raise ValueError("truncated protobuf")
            value = buf[index:end]
            index = end
        elif wire == 5:
            end = index + 4
            if end > size:
                raise ValueError("truncated protobuf")
            value = buf[index:end]
            index = end
        elif wire == 1:
            end = index + 8
            if end > size:
                raise ValueError("truncated protobuf")
            value = buf[index:end]
            index = end
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        yield field, wire, value


def _parse_cidr(buf: bytes) -> tuple[bytes, int]:
    ip = b""
    prefix = 0
    for field, wire, value in _iter_fields(buf):
        if field == 1 and wire == 2:
            ip = value
        elif field == 2 and wire == 0:
            prefix = value
    return ip, prefix


def _parse_geoip(buf: bytes) -> tuple[str, list[tuple[bytes, int]], bool]:
    country = ""
    cidrs = []
    reverse = False
    for field, wire, value in _iter_fields(buf):
        if field == 1 and wire == 2:
            country = value.decode("utf-8")
        elif field == 2 and wire == 2:
            cidrs.append(_parse_cidr(value))
        elif field == 3 and wire == 0:
            reverse = bool(value)
    return country, cidrs, reverse


def parse_geoip_list(buf: bytes) -> list[tuple[str, list[tuple[bytes, int]], bool]]:
    entries = []
    for field, wire, value in _iter_fields(buf):
        if field == 1 and wire == 2:
            entries.append(_parse_geoip(value))
    return entries


def _parse_domain(buf: bytes) -> tuple[int, str]:
    kind = 0
    value = ""
    for field, wire, raw in _iter_fields(buf):
        if field == 1 and wire == 0:
            kind = raw
        elif field == 2 and wire == 2:
            value = raw.decode("utf-8")
    return kind, value


def _parse_geosite(buf: bytes) -> tuple[str, list[tuple[int, str]]]:
    code = ""
    domains = []
    for field, wire, value in _iter_fields(buf):
        if field == 1 and wire == 2:
            code = value.decode("utf-8")
        elif field == 2 and wire == 2:
            domains.append(_parse_domain(value))
    return code, domains


def parse_geosite_list(buf: bytes) -> list[tuple[str, list[tuple[int, str]]]]:
    entries = []
    for field, wire, value in _iter_fields(buf):
        if field == 1 and wire == 2:
            entries.append(_parse_geosite(value))
    return entries


def normalize_domain(domain: str) -> str:
    value = domain.strip().lower().rstrip(".")
    if "://" in value:
        value = value.split("://", 1)[1]
    value = value.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if "@" in value:
        value = value.rsplit("@", 1)[-1]
    if value.startswith("[") and "]" in value:
        value = value[1:value.index("]")]
    elif value.count(":") == 1:
        value = value.split(":", 1)[0]
    return value.strip().rstrip(".")


def _mask(prefix: int, bits: int) -> int:
    if prefix <= 0:
        return 0
    if prefix >= bits:
        return (1 << bits) - 1
    return ((1 << bits) - 1) ^ ((1 << (bits - prefix)) - 1)


class GeoIndex:
    def __init__(self, geoip_entries, geosite_entries):
        self._v4: list[tuple[int, int, int, str, int]] = []
        self._v6: list[tuple[int, int, int, str, int]] = []
        self._full: dict[str, set[str]] = {}
        self._suffix: dict[str, set[str]] = {}
        self._plain: list[tuple[str, str]] = []
        self._regex: list[tuple[re.Pattern[str], str]] = []
        self.skipped_regex = 0
        codes: dict[str, str] = {}
        order = 0
        for country, cidrs, reverse in geoip_entries:
            if reverse:
                continue
            label = codes.setdefault(country.strip(), country.strip())
            if not label:
                continue
            for raw, prefix in cidrs:
                if len(raw) == 4:
                    bits = 32
                    bucket = self._v4
                elif len(raw) == 16:
                    bits = 128
                    bucket = self._v6
                else:
                    continue
                if not 0 <= prefix <= bits:
                    continue
                mask = _mask(prefix, bits)
                network = int.from_bytes(raw, "big") & mask
                bucket.append((network, prefix, mask, label, order))
                order += 1
        for code, domains in geosite_entries:
            category = code.strip()
            if not category:
                continue
            category = codes.setdefault(category, category)
            for kind, raw_value in domains:
                value = raw_value.strip().lower().rstrip(".")
                if not value:
                    continue
                if kind == 0:
                    self._plain.append((value, category))
                elif kind == 1:
                    try:
                        self._regex.append((re.compile(value, re.IGNORECASE), category))
                    except re.error:
                        self.skipped_regex += 1
                elif kind == 2:
                    self._suffix.setdefault(value, set()).add(category)
                elif kind == 3:
                    self._full.setdefault(value, set()).add(category)

    @classmethod
    def load(cls, geoip_path: Path, geosite_path: Path) -> "GeoIndex":
        return cls(
            parse_geoip_list(Path(geoip_path).read_bytes()),
            parse_geosite_list(Path(geosite_path).read_bytes()),
        )

    def country_for_ip(self, ip: str) -> str | None:
        if not ip or not isinstance(ip, str):
            return None
        try:
            address = ipaddress.ip_address(ip.strip())
        except ValueError:
            return None
        if isinstance(address, ipaddress.IPv4Address):
            bucket = self._v4
        else:
            bucket = self._v6
        ip_int = int(address)
        best: tuple[int, int, str] | None = None
        for network, prefix, mask, country, order in bucket:
            if (ip_int & mask) == network:
                if best is None or prefix > best[0] or (prefix == best[0] and order < best[1]):
                    best = (prefix, order, country)
        return None if best is None else best[2]

    def categories_for_domain(self, domain: str) -> list[str]:
        if not isinstance(domain, str):
            return []
        host = normalize_domain(domain)
        if not host:
            return []
        found: set[str] = set()
        full = self._full.get(host)
        if full:
            found.update(full)
        labels = host.split(".")
        for index in range(len(labels)):
            groups = self._suffix.get(".".join(labels[index:]))
            if groups:
                found.update(groups)
        for needle, category in self._plain:
            if needle in host:
                found.add(category)
        for pattern, category in self._regex:
            if pattern.search(host):
                found.add(category)
        return sorted(found)


_CACHE: dict[tuple, GeoIndex] = {}


def clear_geo_cache() -> None:
    _CACHE.clear()


def load_index(directory: Path | None = None) -> GeoIndex:
    folder = Path(directory) if directory is not None else default_data_dir()
    geoip_path = folder / "geoip.dat"
    geosite_path = folder / "geosite.dat"
    missing = [path.name for path in (geoip_path, geosite_path) if not path.is_file()]
    if missing:
        if len(missing) == 1:
            detail = f"{missing[0]} is missing"
        else:
            detail = f"{missing[0]} and {missing[1]} are missing"
        raise FileNotFoundError(
            f"Geo routing is on but {detail} from {folder}. Run scripts/fetch_geo_dat.py."
        )
    key = (
        str(geoip_path.resolve()),
        geoip_path.stat().st_mtime_ns,
        geoip_path.stat().st_size,
        str(geosite_path.resolve()),
        geosite_path.stat().st_mtime_ns,
        geosite_path.stat().st_size,
    )
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    index = GeoIndex.load(geoip_path, geosite_path)
    _CACHE.clear()
    _CACHE[key] = index
    return index
