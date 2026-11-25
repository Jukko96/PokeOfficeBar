"""Find and verify newer portable builds from the official GitHub releases."""

from ctypes import byref, windll
from ctypes.wintypes import DWORD, LPCWSTR, LPDWORD
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
from tempfile import mkdtemp
from threading import Event
from time import monotonic
from urllib.parse import urljoin, urlsplit

import requests

from . import __version__

RELEASES_PAGE = "https://github.com/Jukko96/PokeOfficeBar/releases"
RELEASE_API = "https://api.github.com/repos/Jukko96/PokeOfficeBar/releases/latest"
ASSET_NAME = "PokeOfficeBar.exe"
MAX_ASSET_SIZE = 256 * 1024 * 1024
SCS_64BIT_BINARY = 6
DOWNLOAD_HOSTS = {"github.com", "release-assets.githubusercontent.com",
                  "objects.githubusercontent.com", "github-releases.githubusercontent.com"}


@dataclass(frozen=True)
class Release:
    version: str
    url: str | None = None
    digest: str | None = None
    size: int = 0


@dataclass(frozen=True)
class StagedUpdate:
    directory: Path
    digest: str


def stage_prefix(executable: Path) -> str:
    return f".{executable.name}.update-"


def _version_tuple(tag: str) -> tuple[int, ...] | None:
    match = re.fullmatch(r"v?([0-9]{1,8})\.([0-9]{1,8})\.([0-9]{1,8})", tag)
    return tuple(int(part) for part in match.groups()) if match else None


def check_for_update() -> Release | None:
    response = requests.get(
        RELEASE_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"PokeOfficeBar/{__version__}"},
        timeout=(3, 5), allow_redirects=False,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    if response.status_code != 200:
        raise ValueError("Unexpected GitHub release response status")
    release = response.json()
    if not isinstance(release, dict):
        raise ValueError("Unexpected GitHub release response")
    tag = release.get("tag_name")
    current = _version_tuple(__version__)
    latest = _version_tuple(tag) if isinstance(tag, str) else None
    if current is None or latest is None:
        raise ValueError("Unrecognized release version")
    if (release.get("draft") or release.get("prerelease") or latest <= current):
        return None
    version = "v" + ".".join(map(str, latest))
    url = f"{RELEASES_PAGE}/download/{tag}/{ASSET_NAME}"
    assets = release.get("assets")
    for asset in assets if isinstance(assets, list) else ():
        if not isinstance(asset, dict) or asset.get("name") != ASSET_NAME:
            continue
        digest = asset.get("digest")
        size = asset.get("size")
        if (asset.get("state") == "uploaded" and asset.get("browser_download_url") == url
                and isinstance(digest, str) and re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest)
                and type(size) is int and 0 < size <= MAX_ASSET_SIZE):
            return Release(version, url, digest[7:].lower(), size)
    return Release(version)


def _download_response(url: str) -> requests.Response:
    for _ in range(5):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.netloc.lower() not in DOWNLOAD_HOSTS):
            raise ValueError("Unexpected release download host")
        response = requests.get(url, stream=True, allow_redirects=False, timeout=(5, 15),
                                headers={"Accept-Encoding": "identity"})
        if response.status_code == 200:
            return response
        with response:
            if not response.is_redirect:
                response.raise_for_status()
                raise ValueError("Unexpected release download response")
            url = urljoin(url, response.headers["Location"])
    raise ValueError("Too many release download redirects")


def download_update(release: Release, executable: Path, cancelled: Event) -> StagedUpdate | None:
    if release.url is None or release.digest is None or cancelled.is_set():
        return None
    directory = Path(mkdtemp(prefix=stage_prefix(executable), dir=executable.parent))
    target = directory / "candidate.exe"
    complete = False
    try:
        digest = sha256()
        size = 0
        deadline = monotonic() + 300
        with _download_response(release.url) as response, target.open("xb") as stream:
            for chunk in response.iter_content(256 * 1024):
                if cancelled.is_set():
                    return None
                size += len(chunk)
                if size > release.size or monotonic() > deadline:
                    raise ValueError("Release download exceeded its size or time limit")
                digest.update(chunk)
                stream.write(chunk)
        if size != release.size or digest.hexdigest() != release.digest:
            raise ValueError("Release download did not match its SHA-256 and size")
        get_binary_type = windll.kernel32.GetBinaryTypeW
        get_binary_type.argtypes = [LPCWSTR, LPDWORD]
        binary_type = DWORD()
        if not get_binary_type(str(target.resolve()), byref(binary_type)) or binary_type.value != SCS_64BIT_BINARY:
            raise ValueError("Release asset is not a 64-bit Windows executable")
        complete = True
        return StagedUpdate(directory, release.digest)
    finally:
        if not complete:
            discard_stage(directory)


def discard_stage(directory: Path) -> None:
    """Remove only files created by the updater."""
    for name in ("installer.exe", "candidate.exe", "previous.exe", "ready", "finished"):
        (directory / name).unlink(missing_ok=True)
    directory.rmdir()
