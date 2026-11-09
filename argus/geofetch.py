"""Download pinned v2fly geo data sets and fail closed on checksum mismatch.

Only the v2fly ``geoip`` and ``domain-list-community`` release assets named in
``geo.lock.json`` are accepted. The binaries are written under the gitignored
data directory after the official ``.sha256sum`` asset and the file bytes both
match the lock.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from argus.geo import data_dir

USER_AGENT = "infinitum-argus-geofetch"
MAX_BYTES = 64 * 1024 * 1024
ALLOWED_HOSTS = {
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
}
ALLOWED_DATASETS = {
    "geoip": {
        "upstream": "v2fly/geoip",
        "asset": "geoip.dat",
        "filename": "geoip.dat",
        "sha256sum_asset": "geoip.dat.sha256sum",
        "license": "CC-BY-SA-4.0",
    },
    "geosite": {
        "upstream": "v2fly/domain-list-community",
        "asset": "dlc.dat",
        "filename": "geosite.dat",
        "sha256sum_asset": "dlc.dat.sha256sum",
        "license": "MIT",
    },
}
_FORBIDDEN = ("loyalsoldier", "sing-box", "singbox")


class GeoFetchError(RuntimeError):
    """Raised when a download is refused or a checksum does not match."""


class _ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if code not in (301, 302, 303, 307, 308):
            raise GeoFetchError(f"unsupported redirect {code}")
        parts = urllib.parse.urlsplit(newurl)
        if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
            raise GeoFetchError(f"refusing redirect to {parts.scheme}://{parts.hostname}")
        return urllib.request.Request(newurl, method="GET", headers={"User-Agent": USER_AGENT})


def lock_path() -> Path:
    return Path(__file__).resolve().parents[1] / "geo.lock.json"


def load_lock(path: Path | None = None) -> dict:
    chosen = path or lock_path()
    try:
        payload = json.loads(chosen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GeoFetchError(f"unreadable geo lockfile: {chosen}") from exc
    if not isinstance(payload, dict):
        raise GeoFetchError("geo lockfile must be an object")
    return payload


def _reject_forbidden(blob: str) -> None:
    lowered = blob.casefold()
    for name in _FORBIDDEN:
        if name in lowered:
            raise GeoFetchError(f"refusing geo source that names {name}")


def validate_lock(lock: dict) -> None:
    _reject_forbidden(json.dumps(lock))
    datasets = lock.get("datasets")
    if not isinstance(datasets, list) or len(datasets) != len(ALLOWED_DATASETS):
        raise GeoFetchError("geo lockfile must list the two v2fly data sets")
    seen = set()
    for entry in datasets:
        if not isinstance(entry, dict):
            raise GeoFetchError("geo lock entry must be an object")
        identity = entry.get("id")
        expected = ALLOWED_DATASETS.get(identity)
        if expected is None:
            raise GeoFetchError(f"unknown geo data set {identity!r}")
        if identity in seen:
            raise GeoFetchError(f"duplicate geo data set {identity}")
        seen.add(identity)
        for key, value in expected.items():
            if entry.get(key) != value:
                raise GeoFetchError(f"{identity} {key} must stay {value}")
        tag = entry.get("tag")
        digest = entry.get("sha256")
        size = entry.get("bytes")
        if not isinstance(tag, str) or not tag.isdigit() or not 8 <= len(tag) <= 20:
            raise GeoFetchError(f"{identity} tag is not a release id")
        if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise GeoFetchError(f"{identity} sha256 must be lowercase hex")
        if not isinstance(size, int) or size <= 0 or size > MAX_BYTES:
            raise GeoFetchError(f"{identity} byte size is not pinned")
        upstream = expected["upstream"]
        asset = expected["asset"]
        checksum_name = expected["sha256sum_asset"]
        url = f"https://github.com/{upstream}/releases/download/{tag}/{asset}"
        checksum_url = f"https://github.com/{upstream}/releases/download/{tag}/{checksum_name}"
        if entry.get("url") != url or entry.get("sha256sum_url") != checksum_url:
            raise GeoFetchError(f"{identity} URL does not match the pinned v2fly release")
    if seen != set(ALLOWED_DATASETS):
        raise GeoFetchError("geo lockfile is missing a v2fly data set")


def parse_sha256sum(text: str, asset_name: str) -> str:
    found = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            raise GeoFetchError(f"unreadable sha256sum line for {asset_name}")
        digest, name = parts[0].lower(), parts[1].lstrip("*")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise GeoFetchError(f"unreadable sha256sum digest for {asset_name}")
        if name == asset_name:
            found = digest
    if found is None:
        raise GeoFetchError(f"official sha256sum does not name {asset_name}")
    return found


def _pinned_url(url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS or parts.username or parts.password:
        raise GeoFetchError(f"refusing geo URL host {parts.hostname}")


def download_bytes(url: str) -> bytes:
    _pinned_url(url)
    opener = urllib.request.build_opener(_ReleaseRedirect)
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    try:
        with opener.open(request, timeout=120) as response:
            chunks = []
            total = 0
            while True:
                block = response.read(64 * 1024)
                if not block:
                    break
                total += len(block)
                if total > MAX_BYTES:
                    raise GeoFetchError(f"download exceeded {MAX_BYTES} bytes")
                chunks.append(block)
    except GeoFetchError:
        raise
    except urllib.error.HTTPError as exc:
        raise GeoFetchError(f"download failed for {url}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise GeoFetchError(f"download failed for {url}: {exc.reason}") from exc
    return b"".join(chunks)


def fetch_entry(entry: dict, dest: Path, transport=download_bytes) -> Path:
    official_hash = parse_sha256sum(transport(entry["sha256sum_url"]).decode("utf-8"), entry["asset"])
    locked = entry["sha256"]
    if official_hash != locked:
        raise GeoFetchError(
            "checksum mismatch for "
            f"{entry['filename']}: lock {locked} official {entry['sha256sum_asset']} {official_hash}"
        )
    payload = transport(entry["url"])
    if len(payload) != entry["bytes"]:
        raise GeoFetchError(
            f"size mismatch for {entry['filename']}: lock {entry['bytes']} downloaded {len(payload)}"
        )
    file_hash = hashlib.sha256(payload).hexdigest()
    if file_hash != locked:
        raise GeoFetchError(f"checksum mismatch for {entry['filename']}: lock {locked} file {file_hash}")
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / entry["filename"]
    if target.parent.resolve() != dest.resolve():
        raise GeoFetchError("refusing to write outside the geo data directory")
    partial = target.with_name(target.name + ".partial")
    try:
        partial.write_bytes(payload)
        os.replace(partial, target)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return target


def fetch_all(dest: Path | None = None, transport=download_bytes, lock: dict | None = None) -> list[Path]:
    chosen = lock if lock is not None else load_lock()
    validate_lock(chosen)
    root = dest or data_dir()
    return [fetch_entry(entry, root, transport) for entry in chosen["datasets"]]


def main(argv: list[str] | None = None) -> int:
    del argv
    try:
        written = fetch_all()
    except GeoFetchError as exc:
        print(f"geo fetch stopped: {exc}", file=sys.stderr)
        return 1
    for path in written:
        print(f"verified {path.name} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
