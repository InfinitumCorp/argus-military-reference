import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from argus.dataset import load_dataset
from argus.firmament import FirmamentRecorder
from argus.fusion import ArgusFusionEngine
from argus.geo import GeoIndex, clear_geo_cache, load_index, parse_geoip_list
from argus.geo_fetch import (
    ChecksumMismatch,
    ReleaseRedirect,
    fetch_entries,
    load_lock,
    parse_sha256sum,
    read_https,
    verify_download,
)
from argus.query import SceneQuery
from argus.settings import geo_routing_enabled, load_settings, reset_geo_routing_state
from geo_synth import build_geoip, build_geosite
from main import geo_status_line, main

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GEOIP_SHA256 = "eedb24b3b9fcba27e06b92c0428dab90d9496083091ae4cf39e11387fd99d0e2"
GEOSITE_SHA256 = "dc4192dd1b644a38276ed06136d26e729fa674d25785adb38c87e040e92376b2"


class FakeResponse:
    def __init__(self, data: bytes):
        self._data = data
        self._offset = 0

    def read(self, amount=-1):
        if amount is None or amount < 0:
            amount = len(self._data) - self._offset
        chunk = self._data[self._offset:self._offset + amount]
        self._offset += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeOpener:
    def __init__(self, mapping):
        self.mapping = mapping

    def open(self, request, timeout):
        if request.full_url not in self.mapping:
            raise AssertionError(request.full_url)
        return FakeResponse(self.mapping[request.full_url])


def _entry(name, asset, payload, tag):
    project = "geoip" if name == "geoip.dat" else "domain-list-community"
    digest = hashlib.sha256(payload).hexdigest()
    url = f"https://github.com/v2fly/{project}/releases/download/{tag}/{asset}"
    return {
        "name": name,
        "project": f"v2fly/{project}",
        "tag": tag,
        "asset": asset,
        "url": url,
        "sha256sum_url": url + ".sha256sum",
        "sha256": digest,
        "license": "CC-BY-SA-4.0" if name == "geoip.dat" else "MIT",
    }


class GeoFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = GeoIndex.load(FIXTURES / "geoip.dat", FIXTURES / "geosite.dat")

    def test_fixture_files_match_the_synthetic_encoder(self):
        self.assertEqual((FIXTURES / "geoip.dat").read_bytes(), build_geoip())
        self.assertEqual((FIXTURES / "geosite.dat").read_bytes(), build_geosite())
        self.assertLess((FIXTURES / "geoip.dat").stat().st_size, 4096)
        self.assertLess((FIXTURES / "geosite.dat").stat().st_size, 4096)

    def test_ip_to_country_uses_longest_prefix_and_file_order(self):
        index = self.index
        self.assertEqual(index.country_for_ip("10.1.2.3"), "CN")
        self.assertEqual(index.country_for_ip("10.2.3.4"), "US")
        self.assertEqual(index.country_for_ip("192.0.2.10"), "US")
        self.assertEqual(index.country_for_ip("192.168.1.20"), "PRIVATE")
        self.assertEqual(index.country_for_ip("198.51.100.9"), "FIRST")
        self.assertIsNone(index.country_for_ip("203.0.113.5"))
        self.assertIsNone(index.country_for_ip("8.8.8.8"))
        self.assertIsNone(index.country_for_ip("not-an-ip"))
        self.assertIsNone(index.country_for_ip(""))
        self.assertEqual(index.country_for_ip("2001:db8:1::5"), "JP")
        self.assertEqual(index.country_for_ip("2001:db8:1:2::5"), "KR")

    def test_domain_to_category_follows_v2ray_rules(self):
        index = self.index
        self.assertEqual(index.categories_for_domain("www.google.com"), ["google"])
        self.assertEqual(index.categories_for_domain("GOOGLE.COM."), ["google"])
        self.assertEqual(index.categories_for_domain("https://www.google.com:443/path"), ["google"])
        self.assertEqual(index.categories_for_domain("notgoogle.com"), [])
        self.assertEqual(index.categories_for_domain("tracker.adservice.net"), ["ads"])
        self.assertEqual(index.categories_for_domain("example.com"), ["both", "exact"])
        self.assertEqual(index.categories_for_domain("www.example.com"), ["both"])
        self.assertEqual(index.categories_for_domain("news12.example"), ["news"])
        self.assertEqual(index.categories_for_domain("news.example"), [])
        self.assertEqual(index.skipped_regex, 1)

    def test_truncated_and_unknown_wire_types_fail(self):
        with self.assertRaises(ValueError):
            parse_geoip_list(build_geoip()[:5])
        with self.assertRaises(ValueError):
            parse_geoip_list(b"\x0b")


class GeoSwitchTests(unittest.TestCase):
    def setUp(self):
        self._saved = {
            key: os.environ.get(key)
            for key in ("INFINITUM_GEO_ENABLED", "ARGUS_SETTINGS_PATH", "ARGUS_GEO_DIR")
        }
        self.tmp = tempfile.TemporaryDirectory()
        os.environ.pop("INFINITUM_GEO_ENABLED", None)
        os.environ["ARGUS_SETTINGS_PATH"] = str(Path(self.tmp.name) / "settings.json")
        os.environ["ARGUS_GEO_DIR"] = str(FIXTURES)
        reset_geo_routing_state()
        clear_geo_cache()

    def tearDown(self):
        reset_geo_routing_state()
        clear_geo_cache()
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def observation(self, **extra):
        row = {
            "detection_id": "DET-1",
            "sensor": "CAMERA-NORTH-GATE",
            "lat": 38.9072,
            "lon": -77.0369,
            "alt_m": 2.0,
            "velocity_mps": 1.0,
            "heading_deg": 15.0,
            "raw_class": "person",
            "confidence": 0.8,
        }
        row.update(extra)
        return row

    def test_default_is_off_and_picture_is_unchanged(self):
        self.assertFalse(geo_routing_enabled())
        self.assertFalse(load_settings()["geo_routing"])
        engine = ArgusFusionEngine()
        with self.assertNoLogs("argus.geo", level="INFO"):
            picture = engine.ingest_and_fuse([self.observation(ip="10.1.2.3", domain="www.google.com")])
        self.assertEqual(
            set(picture),
            {"timestamp", "track_count", "alert_count", "tracks", "defense_alerts", "spectrum", "notes", "forecasts"},
        )
        self.assertIsNone(geo_status_line(picture))
        answer = SceneQuery().ask("which country?", picture)["answer"]
        self.assertIn("0 tracks", answer)
        self.assertNotIn("Cyber geo", answer)

    def test_enabled_annotates_without_changing_recommendations(self):
        rows = [
            self.observation(detection_id="A", sensor="POLLEN-SWARM-01", raw_class="uas", is_potential_threat=True),
            self.observation(
                detection_id="B",
                sensor="NEMESIS-FPV-03",
                raw_class="uas",
                is_potential_threat=True,
                ip="10.1.2.3",
                domain="www.google.com",
            ),
        ]
        off = ArgusFusionEngine().ingest_and_fuse(rows)
        os.environ["INFINITUM_GEO_ENABLED"] = "on"
        with self.assertLogs("argus.geo", level="INFO") as captured:
            on = ArgusFusionEngine().ingest_and_fuse(rows)
        self.assertNotIn("geo", off)
        self.assertEqual(
            [item["recommendation"] for item in off["defense_alerts"]],
            [item["recommendation"] for item in on["defense_alerts"]],
        )
        self.assertEqual(
            [item["classification"] for item in off["tracks"]],
            [item["classification"] for item in on["tracks"]],
        )
        self.assertEqual(on["geo"]["source"], "v2fly")
        self.assertEqual(on["geo"]["matches"][0]["country"], "CN")
        self.assertEqual(on["geo"]["matches"][0]["categories"], ["google"])
        self.assertIn("cyber", on["geo"]["note"])
        self.assertTrue(any("cyber geo routing annotated" in line for line in captured.output))
        self.assertIn("Cyber geo routing: on", geo_status_line(on))
        for track in on["tracks"]:
            self.assertNotIn("geo", track)
        recorder = FirmamentRecorder()
        recorder.record_batch(on)
        self.assertTrue(recorder.verify())
        country = SceneQuery().ask("which country?", on)["answer"]
        self.assertIn("CN", country)
        self.assertIn("google", country)
        uas = SceneQuery().ask("What UAS are in the picture?", on)["answer"]
        self.assertIn("UAS", uas)

    def test_missing_datasets_fail_only_when_enabled(self):
        os.environ["ARGUS_GEO_DIR"] = str(Path(self.tmp.name) / "empty")
        os.environ["INFINITUM_GEO_ENABLED"] = "on"
        clear_geo_cache()
        with self.assertRaises(FileNotFoundError):
            ArgusFusionEngine().ingest_and_fuse([self.observation(ip="10.0.0.1")])

    def test_settings_persist_and_env_and_flag_precedence(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            main(["--show-settings"])
        self.assertIn("geo-routing: off", buffer.getvalue())
        self.assertIn("saved: off", buffer.getvalue())
        self.assertFalse(Path(os.environ["ARGUS_SETTINGS_PATH"]).exists())

        with redirect_stdout(io.StringIO()):
            main(["--geo-routing", "on", "--show-settings"])
        saved = json.loads(Path(os.environ["ARGUS_SETTINGS_PATH"]).read_text(encoding="utf-8"))
        self.assertTrue(saved["geo_routing"])
        self.assertTrue(geo_routing_enabled())

        reset_geo_routing_state()
        os.environ["INFINITUM_GEO_ENABLED"] = "off"
        self.assertFalse(geo_routing_enabled())
        self.assertTrue(load_settings()["geo_routing"])

        os.environ["INFINITUM_GEO_ENABLED"] = "maybe"
        with self.assertRaises(ValueError):
            geo_routing_enabled()
        os.environ["INFINITUM_GEO_ENABLED"] = "on"
        self.assertTrue(geo_routing_enabled())

        with redirect_stdout(io.StringIO()):
            main(["--geo-routing", "off", "--show-settings"])
        saved = json.loads(Path(os.environ["ARGUS_SETTINGS_PATH"]).read_text(encoding="utf-8"))
        self.assertFalse(saved["geo_routing"])
        self.assertFalse(geo_routing_enabled())

    def test_sample_csv_is_unchanged_while_off_and_optional_columns_pass_when_on(self):
        sample = load_dataset(str(ROOT / "datasets" / "sample_observations.csv"))
        self.assertEqual(sample[0]["detection_id"], "OBS-0001")
        self.assertNotIn("ip", sample[0])
        self.assertNotIn("domain", sample[0])
        path = Path(self.tmp.name) / "extra.csv"
        path.write_text(
            "detection_id,sensor,lat,lon,raw_class,confidence,ip,host\n"
            "X,CAMERA-NORTH-GATE,1,2,person,0.5,10.2.3.4,www.google.com\n",
            encoding="utf-8",
        )
        hidden = load_dataset(str(path))
        self.assertNotIn("ip", hidden[0])
        os.environ["INFINITUM_GEO_ENABLED"] = "on"
        shown = load_dataset(str(path))
        self.assertEqual(shown[0]["ip"], "10.2.3.4")
        self.assertEqual(shown[0]["domain"], "www.google.com")

    def test_load_index_uses_the_fixture_directory(self):
        first = load_index()
        second = load_index()
        self.assertIs(first, second)
        self.assertEqual(first.country_for_ip("192.0.2.1"), "US")


class GeoFetchTests(unittest.TestCase):
    def test_lockfile_pins_verified_v2fly_assets(self):
        lock = load_lock(ROOT / "geo" / "lock.json")
        geoip, geosite = lock["datasets"]
        self.assertEqual(geoip["sha256"], GEOIP_SHA256)
        self.assertEqual(geoip["tag"], "202611080027")
        self.assertEqual(geoip["asset"], "geoip.dat")
        self.assertEqual(geoip["license"], "CC-BY-SA-4.0")
        self.assertTrue(geoip["url"].startswith("https://github.com/v2fly/geoip/"))
        self.assertEqual(geosite["sha256"], GEOSITE_SHA256)
        self.assertEqual(geosite["tag"], "20261108011013")
        self.assertEqual(geosite["asset"], "dlc.dat")
        self.assertEqual(geosite["name"], "geosite.dat")
        self.assertEqual(geosite["license"], "MIT")
        self.assertTrue(geosite["url"].startswith("https://github.com/v2fly/domain-list-community/"))
        blob = json.dumps(lock).lower()
        self.assertNotIn("loyalsoldier", blob)
        self.assertNotIn("sing-box", blob)
        self.assertNotIn("singbox", blob)
        notices = (ROOT / "THIRD_PARTY_NOTICES").read_text(encoding="utf-8")
        for item in lock["datasets"]:
            self.assertIn(item["sha256"], notices)
            self.assertIn(item["tag"], notices)
            self.assertIn(item["license"], notices)
        self.assertIn("Copyright (c) 2018-2019 V2Ray", notices)
        self.assertIn("DB-IP", notices)
        self.assertEqual(parse_sha256sum(f"{GEOIP_SHA256}  geoip.dat\n"), GEOIP_SHA256)
        self.assertEqual(parse_sha256sum(f"{GEOSITE_SHA256}  dlc.dat\n"), GEOSITE_SHA256)

    def test_checksum_mismatch_writes_nothing(self):
        payload = b"synthetic-geo"
        good = _entry("geoip.dat", "geoip.dat", payload, "202611080027")
        official = f"{good['sha256']}  geoip.dat\n".encode()
        self.assertEqual(verify_download("geoip.dat", official, payload, good["sha256"]), good["sha256"])
        with self.assertRaises(ChecksumMismatch):
            verify_download("geoip.dat", official, b"tampered", good["sha256"])
        with self.assertRaises(ChecksumMismatch):
            verify_download("geoip.dat", b"aa" * 32 + b"  geoip.dat\n", payload, good["sha256"])

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            (dest / "geoip.dat").write_bytes(b"keep")
            opener = FakeOpener({good["sha256sum_url"]: official, good["url"]: b"tampered"})
            with self.assertRaises(ChecksumMismatch):
                fetch_entries([good], dest, opener)
            self.assertEqual((dest / "geoip.dat").read_bytes(), b"keep")
            self.assertFalse((dest / "geosite.dat").exists())

    def test_matching_download_writes_both_names(self):
        geoip_payload = b"geoip-bytes"
        geosite_payload = b"geosite-bytes"
        geoip = _entry("geoip.dat", "geoip.dat", geoip_payload, "202611080027")
        geosite = _entry("geosite.dat", "dlc.dat", geosite_payload, "20261108011013")
        opener = FakeOpener({
            geoip["sha256sum_url"]: f"{geoip['sha256']}  geoip.dat\n".encode(),
            geoip["url"]: geoip_payload,
            geosite["sha256sum_url"]: f"{geosite['sha256']}  dlc.dat\n".encode(),
            geosite["url"]: geosite_payload,
        })
        with tempfile.TemporaryDirectory() as tmp:
            written = fetch_entries([geoip, geosite], Path(tmp), opener)
            self.assertEqual((Path(tmp) / "geoip.dat").read_bytes(), geoip_payload)
            self.assertEqual((Path(tmp) / "geosite.dat").read_bytes(), geosite_payload)
            self.assertEqual(written[1][0].name, "geosite.dat")

    def test_refuses_other_publishers_and_redirects(self):
        payload = b"x"
        bad = _entry("geoip.dat", "geoip.dat", payload, "202611080027")
        bad["url"] = "https://github.com/SagerNet/sing-box/releases/download/v1/geoip.dat"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                fetch_entries([bad], Path(tmp), FakeOpener({}))
            self.assertFalse(any(Path(tmp).iterdir()))
        with self.assertRaises(ValueError):
            read_https(FakeOpener({}), "https://evil.example/geoip.dat", 100)
        request = urllib.request.Request("https://github.com/v2fly/geoip/releases/download/202611080027/geoip.dat")
        with self.assertRaises(urllib.error.HTTPError):
            ReleaseRedirect().redirect_request(request, None, 302, "redirect", {}, "https://evil.example/geoip.dat")
        with self.assertRaises(urllib.error.HTTPError):
            ReleaseRedirect().redirect_request(request, None, 302, "redirect", {}, "http://github.com/v2fly/x")
        allowed = ReleaseRedirect().redirect_request(
            request,
            None,
            302,
            "redirect",
            {},
            "https://release-assets.githubusercontent.com/github-production-release-asset/geoip.dat",
        )
        self.assertIn("githubusercontent.com", allowed.get_full_url())


if __name__ == "__main__":
    unittest.main()
