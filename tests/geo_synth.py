"""Tiny synthetic v2ray geoip.dat and geosite.dat fixtures."""

from pathlib import Path


def _varint(number: int) -> bytes:
    out = bytearray()
    while True:
        piece = number & 0x7F
        number >>= 7
        if number:
            out.append(piece | 0x80)
        else:
            out.append(piece)
            return bytes(out)


def _key(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def _bytes_field(field: int, payload: bytes) -> bytes:
    return _key(field, 2) + _varint(len(payload)) + payload


def _string_field(field: int, text: str) -> bytes:
    return _bytes_field(field, text.encode("utf-8"))


def _varint_field(field: int, number: int) -> bytes:
    return _key(field, 0) + _varint(number)


def _cidr(ip: bytes, prefix: int) -> bytes:
    return _bytes_field(1, ip) + _varint_field(2, prefix)


def _geoip(country: str, cidrs: list[tuple[bytes, int]], reverse: bool = False) -> bytes:
    body = _string_field(1, country)
    for ip, prefix in cidrs:
        body += _bytes_field(2, _cidr(ip, prefix))
    if reverse:
        body += _varint_field(3, 1)
    return body


def _attribute(key: str) -> bytes:
    return _string_field(1, key) + _varint_field(2, 1)


def _domain(kind: int, value: str, attribute: str | None = None) -> bytes:
    body = b""
    if kind:
        body += _varint_field(1, kind)
    body += _string_field(2, value)
    if attribute:
        body += _bytes_field(3, _attribute(attribute))
    return body


def _geosite(code: str, domains: list[tuple[int, str, str | None]]) -> bytes:
    body = _string_field(1, code)
    for kind, value, attribute in domains:
        body += _bytes_field(2, _domain(kind, value, attribute))
    return body


def build_geoip() -> bytes:
    entries = [
        ("US", [(bytes([10, 0, 0, 0]), 8), (bytes([192, 0, 2, 0]), 24)], False),
        ("CN", [(bytes([10, 1, 0, 0]), 16)], False),
        ("FIRST", [(bytes([198, 51, 100, 9]), 32)], False),
        ("SECOND", [(bytes([198, 51, 100, 9]), 32)], False),
        ("PRIVATE", [(bytes([192, 168, 0, 0]), 16)], False),
        ("NOPE", [(bytes([203, 0, 113, 0]), 24)], True),
        ("JP", [(bytes.fromhex("20010db8000100000000000000000000"), 48)], False),
        ("KR", [(bytes.fromhex("20010db8000100020000000000000000"), 64)], False),
    ]
    body = b""
    for country, cidrs, reverse in entries:
        body += _bytes_field(1, _geoip(country, cidrs, reverse))
    return body


def build_geosite() -> bytes:
    groups = [
        ("google", [(2, "google.com", "cn")]),
        ("ads", [(0, "adservice", None)]),
        ("exact", [(3, "example.com", None)]),
        ("both", [(2, "example.com", None)]),
        ("news", [(1, r"^news\d+\.example$", None)]),
        ("broken", [(1, "(", None)]),
    ]
    body = b""
    for code, domains in groups:
        body += _bytes_field(1, _geosite(code, domains))
    return body


def write_fixtures(folder: Path | None = None) -> Path:
    destination = folder or Path(__file__).resolve().parent / "fixtures"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "geoip.dat").write_bytes(build_geoip())
    (destination / "geosite.dat").write_bytes(build_geosite())
    return destination


if __name__ == "__main__":
    print(write_fixtures())
