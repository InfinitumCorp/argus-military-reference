"""v2fly GeoIPList / GeoSiteList loader for cyber observables.

The published ``geoip.dat`` and ``geosite.dat`` files stay outside git.
``INFINITUM_GEO_ENABLED`` defaults off. While off, callers receive no
annotation and product pictures keep their existing keys.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger("argus.cyber.geo")

_TRUTHY = {"1", "true", "yes", "on"}
_DOMAIN_TYPES = {0, 1, 2, 3}
_MAX_HOST_LEN = 253
_MAX_REGEX_LEN = 1024


class GeoDataError(ValueError):
    """Raised when a geo data set or a cyber observable cannot be read."""


def geo_enabled(environ: dict | None = None) -> bool:
    env = os.environ if environ is None else environ
    return env.get("INFINITUM_GEO_ENABLED", "").strip().casefold() in _TRUTHY


def data_dir() -> Path:
    override = os.environ.get("INFINITUM_GEO_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parents[1] / "data" / "geo"


def _varint(buf: memoryview, index: int) -> tuple[int, int]:
    value = 0
    shift = 0
    size = len(buf)
    while shift < 70:
        if index >= size:
            raise GeoDataError("truncated varint")
        byte = buf[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            return value, index
        shift += 7
    raise GeoDataError("varint too wide")


def iter_fields(payload: bytes | memoryview):
    buf = payload if isinstance(payload, memoryview) else memoryview(payload)
    index = 0
    size = len(buf)
    while index < size:
        key, index = _varint(buf, index)
        field, wire = key >> 3, key & 7
        if field <= 0:
            raise GeoDataError("invalid protobuf field")
        if wire == 0:
            value, index = _varint(buf, index)
            yield field, wire, value
        elif wire == 2:
            length, index = _varint(buf, index)
            end = index + length
            if length < 0 or end > size:
                raise GeoDataError("truncated protobuf length")
            yield field, wire, buf[index:end]
            index = end
        elif wire == 1:
            end = index + 8
            if end > size:
                raise GeoDataError("truncated protobuf fixed64")
            yield field, wire, buf[index:end]
            index = end
        elif wire == 5:
            end = index + 4
            if end > size:
                raise GeoDataError("truncated protobuf fixed32")
            yield field, wire, buf[index:end]
            index = end
        else:
            raise GeoDataError(f"unsupported protobuf wire type {wire}")


def _text_field(value) -> str:
    if isinstance(value, int):
        raise GeoDataError("expected a protobuf string")
    try:
        return bytes(value).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GeoDataError("protobuf string is not utf-8") from exc


def _mask(ip: bytes, prefix: int) -> bytes:
    if prefix < 0 or prefix > len(ip) * 8:
        raise GeoDataError("cidr prefix out of range")
    if not prefix:
        return bytes(len(ip))
    full, rem = divmod(prefix, 8)
    out = bytearray(ip[:full])
    if rem:
        mask = (0xFF << (8 - rem)) & 0xFF
        out.append(ip[full] & mask)
        full += 1
    out.extend(b"\x00" * (len(ip) - full))
    return bytes(out)


def _contains(network: bytes, prefix: int, address: bytes) -> bool:
    full, rem = divmod(prefix, 8)
    if network[:full] != address[:full]:
        return False
    if rem == 0:
        return True
    mask = (0xFF << (8 - rem)) & 0xFF
    return network[full] == (address[full] & mask)


def parse_geoip_list(payload: bytes) -> list[tuple[str, list[tuple[bytes, int]], bool]]:
    entries = []
    for field, wire, value in iter_fields(payload):
        if field != 1 or wire != 2:
            continue
        code = ""
        alt_code = ""
        cidrs: list[tuple[bytes, int]] = []
        inverse = False
        for inner, inner_wire, inner_value in iter_fields(value):
            if inner == 1 and inner_wire == 2:
                code = _text_field(inner_value)
            elif inner == 5 and inner_wire == 2:
                alt_code = _text_field(inner_value)
            elif inner == 3 and inner_wire == 0:
                inverse = bool(inner_value)
            elif inner == 2 and inner_wire == 2:
                ip = b""
                prefix = 0
                for cidr_field, cidr_wire, cidr_value in iter_fields(inner_value):
                    if cidr_field == 1 and cidr_wire == 2:
                        ip = bytes(cidr_value)
                    elif cidr_field == 2 and cidr_wire == 0:
                        prefix = int(cidr_value)
                if len(ip) not in (4, 16):
                    raise GeoDataError("cidr address must be 4 or 16 bytes")
                cidrs.append((_mask(ip, prefix), prefix))
        chosen = code or alt_code
        if chosen:
            entries.append((chosen, cidrs, inverse))
    return entries


def parse_geosite_list(payload: bytes) -> list[tuple[str, list[tuple[int, str]]]]:
    lists = []
    for field, wire, value in iter_fields(payload):
        if field != 1 or wire != 2:
            continue
        code = ""
        alt_code = ""
        domains: list[tuple[int, str]] = []
        for inner, inner_wire, inner_value in iter_fields(value):
            if inner == 1 and inner_wire == 2:
                code = _text_field(inner_value)
            elif inner == 4 and inner_wire == 2:
                alt_code = _text_field(inner_value)
            elif inner == 2 and inner_wire == 2:
                dtype = 0
                domain_value = ""
                for domain_field, domain_wire, domain_value_raw in iter_fields(inner_value):
                    if domain_field == 1 and domain_wire == 0:
                        dtype = int(domain_value_raw)
                    elif domain_field == 2 and domain_wire == 2:
                        domain_value = _text_field(domain_value_raw)
                if dtype in _DOMAIN_TYPES and domain_value:
                    domains.append((dtype, domain_value))
        chosen = code or alt_code
        if chosen:
            lists.append((chosen, domains))
    return lists


class GeoIPIndex:
    """Longest-prefix country lookup. Inverse lists are not countries."""

    def __init__(self, entries: list[tuple[str, list[tuple[bytes, int]], bool]]):
        self.inverse_lists = 0
        self._v4 = [[] for _ in range(256)]
        self._v4_wide: list[tuple[int, int, bytes, str]] = []
        self._v6 = [[] for _ in range(256)]
        self._v6_wide: list[tuple[int, int, bytes, str]] = []
        order = 0
        for code, cidrs, inverse in entries:
            if inverse:
                self.inverse_lists += 1
                continue
            for network, prefix in cidrs:
                bucket_list, wide = (self._v4, self._v4_wide) if len(network) == 4 else (self._v6, self._v6_wide)
                row = (prefix, order, network, code)
                if prefix >= 8:
                    bucket_list[network[0]].append(row)
                else:
                    wide.append(row)
                order += 1

    def lookup(self, ip: str) -> str | None:
        try:
            address = ipaddress.ip_address(ip.strip())
        except ValueError as exc:
            raise GeoDataError("unrecognized address") from exc
        mapped = getattr(address, "ipv4_mapped", None)
        if mapped is not None:
            address = mapped
        packed = address.packed
        if len(packed) == 4:
            rows = self._v4_wide + self._v4[packed[0]]
        else:
            rows = self._v6_wide + self._v6[packed[0]]
        best_prefix = -1
        best_order = 0
        best_code = None
        for prefix, order, network, code in rows:
            if prefix < best_prefix:
                continue
            if not _contains(network, prefix, packed):
                continue
            if prefix > best_prefix or order < best_order:
                best_prefix = prefix
                best_order = order
                best_code = code
        return best_code


class GeoSiteIndex:
    def __init__(self, lists: list[tuple[str, list[tuple[int, str]]]]):
        self.full: dict[str, list[str]] = {}
        self.domain: dict[str, list[str]] = {}
        self.plain: list[tuple[str, str]] = []
        self.regex: list[tuple[re.Pattern[str], str]] = []
        self.skipped_regex = 0
        for code, domains in lists:
            for dtype, value in domains:
                if dtype == 1:
                    pattern = value.strip().casefold()
                    if not pattern or len(pattern) > _MAX_REGEX_LEN:
                        self.skipped_regex += 1
                        continue
                    try:
                        self.regex.append((re.compile(pattern), code))
                    except re.error:
                        self.skipped_regex += 1
                    continue
                try:
                    normalized = normalize_domain(value)
                except GeoDataError:
                    continue
                if dtype == 3:
                    self.full.setdefault(normalized, []).append(code)
                elif dtype == 2:
                    self.domain.setdefault(normalized, []).append(code)
                elif dtype == 0:
                    self.plain.append((normalized, code))

    def lookup(self, domain: str) -> list[str]:
        host = normalize_domain(domain)
        found: list[str] = []
        labels = host.split(".")
        for start in range(len(labels)):
            suffix = ".".join(labels[start:])
            if start == 0:
                found.extend(self.full.get(suffix, ()))
            found.extend(self.domain.get(suffix, ()))
        for needle, code in self.plain:
            if needle in host:
                found.append(code)
        for pattern, code in self.regex:
            if pattern.search(host):
                found.append(code)
        return sorted(set(found))


def normalize_domain(value: str) -> str:
    host = value.strip().rstrip(".").casefold()
    if host.startswith("[") and "]" in host:
        raise GeoDataError("unrecognized domain")
    if host.count(":") == 1:
        name, port = host.rsplit(":", 1)
        if port.isdigit():
            host = name
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise GeoDataError("unrecognized domain") from exc
    if not host or len(host) > _MAX_HOST_LEN or ".." in host:
        raise GeoDataError("unrecognized domain")
    return host


class GeoLibrary:
    _cache: tuple | None = None

    def __init__(self, geoip: GeoIPIndex, geosite: GeoSiteIndex):
        self.geoip = geoip
        self.geosite = geosite

    @classmethod
    def from_bytes(cls, geoip_payload: bytes, geosite_payload: bytes) -> "GeoLibrary":
        return cls(GeoIPIndex(parse_geoip_list(geoip_payload)), GeoSiteIndex(parse_geosite_list(geosite_payload)))

    @classmethod
    def load(cls, geoip_path: Path | str, geosite_path: Path | str) -> "GeoLibrary":
        return cls.from_bytes(Path(geoip_path).read_bytes(), Path(geosite_path).read_bytes())

    @classmethod
    def load_default(cls) -> "GeoLibrary":
        root = data_dir()
        paths = (root / "geoip.dat", root / "geosite.dat")
        missing = [path.name for path in paths if not path.is_file()]
        if missing:
            names = ", ".join(missing)
            raise GeoDataError(f"missing {names} in {root}. Run scripts/fetch_geo.py")
        signature = tuple((path.name, path.stat().st_mtime_ns, path.stat().st_size) for path in paths)
        cached = cls._cache
        if cached is not None and cached[0] == signature:
            return cached[1]
        library = cls.load(paths[0], paths[1])
        cls._cache = (signature, library)
        return library

    def lookup_ip(self, ip: str) -> str | None:
        return self.geoip.lookup(ip)

    def lookup_domain(self, domain: str) -> list[str]:
        return self.geosite.lookup(domain)

    def annotate(self, observations: list[dict]) -> dict:
        rows = []
        for obs in observations:
            source_ip = _optional_text(obs, "source_ip")
            domain = _optional_text(obs, "domain")
            if source_ip is None and domain is None:
                continue
            row: dict = {}
            detection_id = _optional_text(obs, "detection_id")
            if detection_id is not None:
                row["detection_id"] = detection_id
            if source_ip is not None:
                row["source_ip"] = source_ip
                try:
                    row["country"] = self.lookup_ip(source_ip)
                except GeoDataError:
                    row["country"] = None
                    row["address_error"] = "unrecognized address"
            if domain is not None:
                row["domain"] = domain
                try:
                    row["categories"] = self.lookup_domain(domain)
                except GeoDataError:
                    row["categories"] = []
                    row["domain_error"] = "unrecognized domain"
            rows.append(row)
        logger.info("cyber geo annotated %d observable(s)", len(rows))
        return {
            "enabled": True,
            "advisory": "cyber geo annotation only; recommendations unchanged",
            "policy": {
                "name": "cyber-geo",
                "effect": "annotate",
                "mutates_recommendations": False,
            },
            "observables": rows,
        }


def _optional_text(obs: dict, key: str) -> str | None:
    value = obs.get(key)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def annotate_cyber_geo(observations: list[dict], library: GeoLibrary | None = None) -> dict | None:
    """Return a cyber geo annotation, or None when the feature is off.

    The disabled path does not read data files and does not mutate ``observations``.
    """
    if not geo_enabled():
        return None
    chosen = library if library is not None else GeoLibrary.load_default()
    return chosen.annotate(observations)
