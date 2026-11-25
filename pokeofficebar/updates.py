"""Read the latest stable release metadata from the project's GitHub repository."""

import re

import requests

from . import __version__

RELEASES_PAGE = "https://github.com/Jukko96/PokeOfficeBar/releases"
RELEASE_API = "https://api.github.com/repos/Jukko96/PokeOfficeBar/releases/latest"


def _version_tuple(tag: str) -> tuple[int, ...] | None:
    match = re.fullmatch(r"v?([0-9]{1,8})\.([0-9]{1,8})\.([0-9]{1,8})", tag)
    return tuple(int(part) for part in match.groups()) if match else None


def check_for_update() -> str | None:
    response = requests.get(
        RELEASE_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"PokeOfficeBar/{__version__}"},
        timeout=(3, 5),
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
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
    return "v" + ".".join(map(str, latest))
