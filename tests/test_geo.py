import hashlib
import ipaddress
import json
import os
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from argus.dataset import load_dataset
from argus.fusion import ArgusFusionEngine
from argus.geo import GeoDataError, GeoLibrary, annotate_cyber_geo, geo_enabled
from argus.geofetch import (
    GeoFetchError,
    _ReleaseRedirect,
    fetch_entry,
    load_lock,
    parse_sha256sum,
    validate_lock,
)
from argus.streaming import StreamingProcessor

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "geo"
GEOIP_SHA = "eedb24b3b9fcba27e06b92c0428dab90d9496083091ae4cf39e11387fd99d0e2"
GEOSITE_SHA = "dc4192dd1b644a38276ed06136d26e729fa674d25785adb38c87e040e92376b2"


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _key(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def _bytes_field(field: int, payload: bytes) -> bytes:
    return _key(field, 2) + _varint(len(payload)) + payload


def _varint_field(field: int, value: int) -> bytes:
    return _key(field, 0) + _varint(value)


def _cidr(address: str, prefix: int, extra: bytes | None = None) -> bytes:
    body = _bytes_field(1, ipaddress.ip_address(address).packed) + _varint_field(2, prefix)
    if extra is not None:
        body += _bytes_field(68000, extra)
    return body


def _geoip(code: str, cidrs: list[bytes], *, inverse: bool = False, resource: bytes | None = None) -> bytes:
    body = _bytes_field(1, code.encode())
    for cidr in cidrs:
        body += _bytes_field(2, cidr)
    if inverse:
        body += _varint_field(3, 1)
    if resource is not None:
        body += _bytes_field(4, resource)
    return body


def sample_geoip_bytes() -> bytes:
    entries = [
        _geoip("HALF", [_cidr("0.0.0.0", 1)]),
        _geoip("PRIVATE", [_cidr("10.0.0.0", 8)]),
        _geoip("EX", [_cidr("192.0.2.0", 24, b"192.0.2.0")], resource=b"\x01\x02"),
        _geoip("EX2", [_cidr("192.0.2.128", 25)]),
        _geoip("ZZ", [_cidr("192.0.2.0", 24)]),
        _geoip("V6", [_cidr("2001:db8::", 32)]),
        _geoip("WIDE", [_cidr("0.0.0.0", 0)], inverse=True),
    ]
    return b"".join(_bytes_field(1, entry) for entry in entries)


def _domain(value: str, dtype: int | None = None, attr: str | None = None) -> bytes:
    body = b""
    if dtype is not None:
        body += _varint_field(1, dtype)
    body += _bytes_field(2, value.encode())
    if attr is not None:
        body += _bytes_field(3, _bytes_field(1, attr.encode()))
    return body


def _site(code: str, domains: list[bytes], *, extra: bool = False) -> bytes:
    body = _bytes_field(1, code.encode())
    for domain in domains:
        body += _bytes_field(2, domain)
    if extra:
        body += _bytes_field(3, b"\x01\x02")
        body += _bytes_field(68000, b"skip")
    return body


def sample_geosite_bytes() -> bytes:
    sites = [
        _site("fullcat", [_domain("exact.example", 3, attr="cn")], extra=True),
        _site("domcat", [_domain("example.com", 2)]),
        _site("alt", [_domain("example.com", 2)]),
        _site("plaincat", [_domain("ads")]),
        _site("regexcat", [_domain(r"^news[0-9]+\.example$", 1)]),
    ]
    return b"".join(_bytes_field(1, site) for site in sites)


def _library() -> GeoLibrary:
    return GeoLibrary.from_bytes(sample_geoip_bytes(), sample_geosite_bytes())


def _observation(detection_id: str, **extra):
    obs = {
        "detection_id": detection_id,
        "sensor": "CAMERA-NORTH-GATE" if detection_id.endswith("1") else "EON-WEARABLE-07",
        "timestamp": "2026-11-05T18:00:01Z",
        "lat": 38.9072,
        "lon": -77.0369,
        "alt_m": 1.0,
        "velocity_mps": 1.0,
        "heading_deg": 10.0,
        "raw_class": "person",
        "confidence": 0.8,
        "spectrum_anomaly": False,
        "is_potential_threat": False,
    }
    obs.update(extra)
    return obs


class GeoFixtureTests(unittest.TestCase):
    def test_committed_fixtures_match_the_synthetic_encoder(self):
        geoip = (FIXTURE / "geoip.dat").read_bytes()
        geosite = (FIXTURE / "geosite.dat").read_bytes()
        self.assertEqual(geoip, sample_geoip_bytes())
        self.assertEqual(geosite, sample_geosite_bytes())
        self.assertLess(len(geoip) + len(geosite), 4096)
        self.assertNotEqual(hashlib.sha256(geoip).hexdigest(), GEOIP_SHA)

    def test_ip_and_domain_lookups(self):
        library = GeoLibrary.load(FIXTURE / "geoip.dat", FIXTURE / "geosite.dat")
        self.assertEqual(library.lookup_ip("10.1.2.3"), "PRIVATE")
        self.assertEqual(library.lookup_ip("192.0.2.10"), "EX")
        self.assertEqual(library.lookup_ip("192.0.2.200"), "EX2")
        self.assertEqual(library.lookup_ip("::ffff:192.0.2.10"), "EX")
        self.assertEqual(library.lookup_ip("8.8.8.8"), "HALF")
        self.assertIsNone(library.lookup_ip("200.1.1.1"))
        self.assertEqual(library.lookup_ip("2001:db8::1"), "V6")
        self.assertIsNone(library.lookup_ip("2001:db9::1"))
        self.assertEqual(library.geoip.inverse_lists, 1)
        with self.assertRaises(GeoDataError):
            library.lookup_ip("not-an-address")
        self.assertEqual(library.lookup_domain("exact.example"), ["fullcat"])
        self.assertEqual(library.lookup_domain("www.exact.example"), [])
        self.assertEqual(library.lookup_domain("a.example.com"), ["alt", "domcat"])
        self.assertEqual(library.lookup_domain("example.com."), ["alt", "domcat"])
        self.assertEqual(library.lookup_domain("notexample.com"), [])
        self.assertEqual(library.lookup_domain("example.com.evil"), [])
        self.assertEqual(library.lookup_domain("tracker.ads.net"), ["plaincat"])
        self.assertEqual(library.lookup_domain("news12.example"), ["regexcat"])
        self.assertEqual(library.lookup_domain("News12.example:443"), ["regexcat"])

    def test_truncated_payload_is_rejected(self):
        with self.assertRaises(GeoDataError):
            GeoLibrary.from_bytes(b"\x0a\x05", sample_geosite_bytes())


class GeoHookTests(unittest.TestCase):
    def setUp(self):
        self._saved = {key: os.environ.get(key) for key in ("INFINITUM_GEO_ENABLED", "INFINITUM_GEO_DIR")}
        os.environ.pop("INFINITUM_GEO_ENABLED", None)
        os.environ.pop("INFINITUM_GEO_DIR", None)
        GeoLibrary._cache = None

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        GeoLibrary._cache = None

    def test_flag_defaults_off(self):
        self.assertFalse(geo_enabled())
        self.assertTrue(geo_enabled({"INFINITUM_GEO_ENABLED": "yes"}))
        self.assertFalse(geo_enabled({"INFINITUM_GEO_ENABLED": "0"}))
        observations = [_observation("OBS-1", source_ip="10.1.2.3", domain="a.example.com")]
        with patch("argus.geo.GeoLibrary.load_default", side_effect=AssertionError("data must stay unread")):
            self.assertIsNone(annotate_cyber_geo(observations))
        self.assertNotIn("country", observations[0])

    def test_annotation_is_advisory_and_logs_counts_only(self):
        observations = [
            _observation("OBS-1", source_ip="10.1.2.3", domain="a.example.com"),
            _observation("OBS-2", source_ip="not-an-address", domain="example.com.evil"),
            _observation("OBS-3"),
        ]
        with patch.dict(os.environ, {"INFINITUM_GEO_ENABLED": "true"}):
            with self.assertLogs("argus.cyber.geo", level="INFO") as logs:
                note = annotate_cyber_geo(observations, library=_library())
        self.assertEqual(len(note["observables"]), 2)
        self.assertNotIn("10.1.2.3", " ".join(logs.output))
        first = note["observables"][0]
        self.assertEqual(first["country"], "PRIVATE")
        self.assertEqual(first["categories"], ["alt", "domcat"])
        self.assertFalse(note["policy"]["mutates_recommendations"])
        self.assertEqual(note["observables"][1]["country"], None)
        self.assertEqual(note["observables"][1]["address_error"], "unrecognized address")
        self.assertEqual(note["observables"][1]["categories"], [])

    def test_fusion_picture_is_unchanged_until_the_flag_is_on(self):
        observations = [
            _observation("OBS-1", source_ip="192.0.2.200", domain="exact.example"),
            _observation("OBS-2", source_ip="192.0.2.200", domain="exact.example"),
        ]
        with patch("argus.geo.GeoLibrary.load_default", side_effect=AssertionError("data must stay unread")):
            disabled = ArgusFusionEngine().ingest_and_fuse(observations)
        self.assertNotIn("cyber_geo", disabled)
        with patch.dict(os.environ, {"INFINITUM_GEO_ENABLED": "on"}):
            with patch("argus.geo.GeoLibrary.load_default", return_value=_library()):
                enabled = ArgusFusionEngine().ingest_and_fuse(observations)
        self.assertEqual(enabled["track_count"], disabled["track_count"])
        self.assertEqual(enabled["alert_count"], disabled["alert_count"])
        self.assertEqual(enabled["notes"], disabled["notes"])
        self.assertEqual(enabled["forecasts"][0]["type"], disabled["forecasts"][0]["type"])
        self.assertEqual(enabled["spectrum"], disabled["spectrum"])
        self.assertEqual(set(enabled) - {"cyber_geo"}, set(disabled))
        self.assertEqual(enabled["cyber_geo"]["observables"][0]["country"], "EX2")
        self.assertEqual(enabled["cyber_geo"]["observables"][0]["categories"], ["fullcat"])
        self.assertEqual(enabled["defense_alerts"], disabled["defense_alerts"])

    def test_streaming_keeps_the_default_history_shape(self):
        processor = StreamingProcessor()
        picture = processor.process_batch([_observation("OBS-1"), _observation("OBS-2")])
        self.assertNotIn("cyber_geo", picture)
        self.assertEqual(set(processor.history[0]), {"timestamp", "track_count", "alert_count"})

    def test_csv_preserves_cyber_fields_only_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            bare = Path(tmp) / "bare.csv"
            bare.write_text(
                "detection_id,timestamp,sensor,lat,lon,raw_class\n"
                "OBS-1,2026-11-05T18:00:01Z,CAMERA-NORTH-GATE,1,2,person\n",
                encoding="utf-8",
            )
            rich = Path(tmp) / "rich.csv"
            rich.write_text(
                "detection_id,timestamp,sensor,lat,lon,raw_class,source_ip,domain\n"
                "OBS-1,2026-11-05T18:00:01Z,CAMERA-NORTH-GATE,1,2,person,10.1.2.3,a.example.com\n",
                encoding="utf-8",
            )
            plain = load_dataset(str(bare))[0]
            annotated = load_dataset(str(rich))[0]
        self.assertNotIn("source_ip", plain)
        self.assertNotIn("domain", plain)
        self.assertEqual(annotated["source_ip"], "10.1.2.3")
        self.assertEqual(annotated["domain"], "a.example.com")


class GeoFetchTests(unittest.TestCase):
    def test_lock_pins_v2fly_checksums(self):
        lock = load_lock(ROOT / "geo.lock.json")
        validate_lock(lock)
        by_id = {entry["id"]: entry for entry in lock["datasets"]}
        self.assertEqual(by_id["geoip"]["sha256"], GEOIP_SHA)
        self.assertEqual(by_id["geoip"]["tag"], "202611080027")
        self.assertEqual(by_id["geosite"]["sha256"], GEOSITE_SHA)
        self.assertEqual(by_id["geosite"]["asset"], "dlc.dat")
        self.assertEqual(by_id["geosite"]["filename"], "geosite.dat")

    def test_other_publishers_are_refused(self):
        lock = json.loads((ROOT / "geo.lock.json").read_text(encoding="utf-8"))
        lock["datasets"][0]["upstream"] = "Loyalsoldier/v2ray-rules-dat"
        with self.assertRaises(GeoFetchError):
            validate_lock(lock)

    def test_sha256sum_parser_accepts_binary_marker(self):
        digest = "ab" * 32
        self.assertEqual(parse_sha256sum(f"{digest} *dlc.dat\n", "dlc.dat"), digest)

    def test_checksum_mismatch_writes_nothing(self):
        lock = load_lock(ROOT / "geo.lock.json")
        entry = lock["datasets"][0]

        def official_disagrees(url: str) -> bytes:
            self.assertTrue(url.startswith("https://github.com/v2fly/"))
            if url.endswith(".sha256sum"):
                return f"{'ab' * 32}  geoip.dat\n".encode()
            raise AssertionError("payload must not be fetched after checksum mismatch")

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(GeoFetchError) as caught:
                fetch_entry(entry, Path(tmp), official_disagrees)
            self.assertIn("checksum mismatch", str(caught.exception))
            self.assertIn(GEOIP_SHA, str(caught.exception))
            self.assertIn("ab" * 32, str(caught.exception))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_file_hash_mismatch_writes_nothing(self):
        entry = {
            "filename": "geoip.dat",
            "asset": "geoip.dat",
            "sha256": "cd" * 32,
            "bytes": 4,
            "url": "https://github.com/v2fly/geoip/releases/download/202611080027/geoip.dat",
            "sha256sum_url": "https://github.com/v2fly/geoip/releases/download/202611080027/geoip.dat.sha256sum",
            "sha256sum_asset": "geoip.dat.sha256sum",
        }

        def transport(url: str) -> bytes:
            if url.endswith(".sha256sum"):
                return b"cd" * 32 + b"  geoip.dat\n"
            return b"nope"

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(GeoFetchError) as caught:
                fetch_entry(entry, Path(tmp), transport)
            self.assertIn("file " + hashlib.sha256(b"nope").hexdigest(), str(caught.exception))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_matching_bytes_are_written_only_after_both_checks(self):
        payload = sample_geoip_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        entry = {
            "filename": "geoip.dat",
            "asset": "geoip.dat",
            "sha256": digest,
            "bytes": len(payload),
            "url": "https://github.com/v2fly/geoip/releases/download/202611080027/geoip.dat",
            "sha256sum_url": "https://github.com/v2fly/geoip/releases/download/202611080027/geoip.dat.sha256sum",
            "sha256sum_asset": "geoip.dat.sha256sum",
        }

        def transport(url: str) -> bytes:
            if url.endswith(".sha256sum"):
                return f"{digest}  geoip.dat\n".encode()
            return payload

        with tempfile.TemporaryDirectory() as tmp:
            written = fetch_entry(entry, Path(tmp), transport)
            self.assertEqual(written.read_bytes(), payload)
            self.assertEqual(list(Path(tmp).iterdir()), [written])

    def test_redirects_stay_on_https_release_hosts(self):
        handler = _ReleaseRedirect()
        request = urllib.request.Request("https://github.com/v2fly/geoip/releases/download/202611080027/geoip.dat")
        with self.assertRaises(GeoFetchError):
            handler.redirect_request(request, None, 302, "found", {}, "http://evil.example/geoip.dat")
        with self.assertRaises(GeoFetchError):
            handler.redirect_request(request, None, 302, "found", {}, "https://evil.example/geoip.dat")
        allowed = handler.redirect_request(
            request, None, 302, "found", {}, "https://release-assets.githubusercontent.com/geoip.dat"
        )
        self.assertIsNone(allowed.get_header("Authorization"))

    def test_fetched_binaries_are_gitignored(self):
        import subprocess

        for name in ("data/geo/geoip.dat", "data/geo/geosite.dat"):
            result = subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT, check=False)
            self.assertEqual(result.returncode, 0, name)


if __name__ == "__main__":
    unittest.main()
