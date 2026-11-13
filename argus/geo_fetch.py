"""Download the pinned v2fly geoip.dat and geosite.dat release assets.

Official .sha256sum bytes, the lockfile digest, and the file bytes must all
agree. A mismatch raises ChecksumMismatch before the data directory is written.
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MAX_DAT_BYTES = 40 * 1024 * 1024
MAX_SUM_BYTES = 4096
_NAMES = ("geoip.dat", "geosite.dat")


class ChecksumMismatch(Exception):
    """Official sha256sum or downloaded bytes do not match the lockfile."""


def lockfile_path() -> Path:
    return Path(__file__).resolve().parents[1] / "geo" / "lock.json"


def data_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "geo"


def parse_sha256sum(text: str | bytes) -> str:
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    stripped = text.strip()
    if not stripped:
        raise ValueError("sha256sum asset is empty")
    token = stripped.splitlines()[0].split()[0].lower()
    if len(token) != 64 or any(character not in "0123456789abcdef" for character in token):
        raise ValueError("sha256sum asset is not a SHA-256 digest")
    return token


def verify_download(name: str, official_text: str | bytes, payload: bytes, lock_hash: str) -> str:
    official = parse_sha256sum(official_text)
    expected = lock_hash.lower()
    digest = hashlib.sha256(payload).hexdigest()
    if official != expected:
        raise ChecksumMismatch(
            f"official sha256sum for {name} does not match lockfile ({official} != {expected})"
        )
    if digest != expected:
        raise ChecksumMismatch(f"checksum mismatch for {name} ({digest} != {expected})")
    return digest


def _host_allowed(hostname: str | None) -> bool:
    host = (hostname or "").lower()
    return host == "github.com" or host.endswith(".githubusercontent.com")


class ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    """Follow only HTTPS release-asset hosts. Application routes are untouched."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urllib.parse.urlsplit(newurl)
        if parts.scheme != "https" or parts.username or parts.password or not _host_allowed(parts.hostname):
            raise urllib.error.HTTPError(req.full_url, code, "geo fetch redirect refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def build_opener():
    return urllib.request.build_opener(ReleaseRedirect)


def _require_v2fly(entry: dict) -> None:
    name = entry.get("name")
    if name not in _NAMES:
        raise ValueError(f"unexpected dataset {name}")
    digest = str(entry.get("sha256", "")).lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"lockfile SHA-256 for {name} is invalid")
    tag = str(entry.get("tag", ""))
    asset = str(entry.get("asset", ""))
    if not tag or not asset:
        raise ValueError(f"lockfile tag or asset for {name} is missing")
    for key in ("url", "sha256sum_url"):
        url = str(entry.get(key, ""))
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or parts.hostname != "github.com" or parts.username or parts.password or parts.query:
            raise ValueError(f"{key} must be a credential-free https://github.com URL")
        if not parts.path.startswith("/v2fly/") or ".." in parts.path:
            raise ValueError(f"{key} is not a v2fly release asset")
        if tag not in parts.path:
            raise ValueError(f"{key} does not include the pinned tag for {name}")
    if asset not in urllib.parse.urlsplit(str(entry["url"])).path:
        raise ValueError(f"url does not include asset {asset}")
    if not str(entry["sha256sum_url"]).endswith(".sha256sum"):
        raise ValueError(f"sha256sum_url for {name} must end with .sha256sum")


def load_lock(path: Path | None = None) -> dict:
    lock_path = path or lockfile_path()
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    datasets = data.get("datasets") if isinstance(data, dict) else None
    if not isinstance(datasets, list) or [item.get("name") for item in datasets] != list(_NAMES):
        raise ValueError("lockfile must list geoip.dat then geosite.dat")
    for item in datasets:
        _require_v2fly(item)
    return data


def read_https(opener, url: str, limit: int) -> bytes:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname != "github.com" or parts.username or parts.password:
        raise ValueError("refusing non-GitHub URL")
    request = urllib.request.Request(url, headers={"User-Agent": "argus-geo-fetch"})
    with opener.open(request, timeout=60) as response:
        chunks = []
        total = 0
        while True:
            block = response.read(64 * 1024)
            if not block:
                break
            total += len(block)
            if total > limit:
                raise ValueError("download exceeds size limit")
            chunks.append(block)
        return b"".join(chunks)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_bytes(payload)
    temporary.replace(path)


def fetch_entries(entries: list[dict], dest_dir: Path, opener) -> list[tuple[Path, str]]:
    staged = []
    for entry in entries:
        _require_v2fly(entry)
        official = read_https(opener, entry["sha256sum_url"], MAX_SUM_BYTES)
        payload = read_https(opener, entry["url"], MAX_DAT_BYTES)
        digest = verify_download(entry["name"], official, payload, entry["sha256"])
        staged.append((entry["name"], payload, digest))
    written = []
    for name, payload, digest in staged:
        path = Path(dest_dir) / name
        _atomic_write(path, payload)
        written.append((path, digest))
    return written


def main() -> int:
    try:
        written = fetch_entries(load_lock()["datasets"], data_dir(), build_opener())
    except (ChecksumMismatch, ValueError, urllib.error.URLError, OSError) as exc:
        print(f"geo fetch failed: {exc}", file=sys.stderr)
        return 1
    for path, digest in written:
        print(f"verified {path.name} sha256 {digest}")
    return 0
