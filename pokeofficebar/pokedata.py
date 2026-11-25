"""Species, evolution lines, and sprites from PokeAPI.

Two CSVs from the PokeAPI repo carry everything the game needs — evolution
parentage, capture rates, legendary flags, and localized names. Offline builds
include those tables and the Gen-V sprites alongside the application.
"""

from __future__ import annotations

import csv
import io
import sys
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile

import requests
from PIL import Image, ImageSequence

CSV_BASE = "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv"
POKEMON_SPRITE_BASE = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon"
SPRITE_BASE = f"{POKEMON_SPRITE_BASE}/versions/generation-v/black-white/animated"
ITEM_BASE = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items"
EGG_URL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/egg.png"

MAX_GENERATION = 5          # Gen 1-5 have animated sprites
LANG_EN, LANG_KO = "9", "3"

# capture_rate -> rarity. Lower capture rate means harder to catch, so rarer.
RARITY_TIERS = [
    (150, "Common"),
    (90, "Uncommon"),
    (45, "Rare"),
    (0, "Very Rare"),
]


def _valid_sprite(source, expected: str) -> bool:
    try:
        with Image.open(source) as image:
            if image.format != expected:
                return False
            for frame in ImageSequence.Iterator(image):
                frame.load()
        return True
    except (OSError, ValueError, SyntaxError):
        return False


@lru_cache(maxsize=1024)
def _valid_cached_sprite(path: Path, mtime_ns: int, size: int) -> bool:
    return bool(size) and _valid_sprite(path, path.suffix[1:].upper())


def _usable_sprite(path: Path) -> bool:
    try:
        info = path.stat()
    except OSError:
        return False
    return _valid_cached_sprite(path, info.st_mtime_ns, info.st_size)


@dataclass(slots=True)
class Species:
    id: int
    identifier: str
    generation: int
    evolves_from: int | None
    chain_id: int
    capture_rate: int
    is_legendary: bool
    is_mythical: bool
    names: dict[str, str] = field(default_factory=dict)
    children: list[int] = field(default_factory=list)

    def name(self, lang: str = "en") -> str:
        key = LANG_KO if lang == "ko" else LANG_EN
        return self.names.get(key) or self.identifier.replace("-", " ").title()

    @property
    def rarity(self) -> str:
        if self.is_legendary or self.is_mythical:
            return "Legendary"
        for threshold, label in RARITY_TIERS:
            if self.capture_rate >= threshold:
                return label
        return "Very Rare"


class Pokedex:
    """The full Gen 1-5 species table and sprite library."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.sprite_dir = cache_dir / "sprites"
        self.item_dir = cache_dir / "items"
        base = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)
        self.bundle_dir = Path(base) / "pokemon_data"
        self.sprite_dir.mkdir(parents=True, exist_ok=True)
        self.item_dir.mkdir(parents=True, exist_ok=True)
        self.species: dict[int, Species] = {}
        self.bases: list[int] = []
        self._lock = threading.Lock()

    # ---- data ------------------------------------------------------

    def _bundled_file(self, *parts: str) -> Path | None:
        path = self.bundle_dir.joinpath(*parts)
        return path if path.is_file() else None

    def has_local_tables(self) -> bool:
        return all(self._bundled_file(name) or (self.cache_dir / name).is_file()
                   for name in ("pokemon_species.csv", "pokemon_species_names.csv"))

    def _fetch_csv(self, name: str) -> str:
        bundled = self._bundled_file(f"{name}.csv")
        if bundled is not None:
            return bundled.read_text(encoding="utf-8-sig")
        path = self.cache_dir / f"{name}.csv"
        if path.exists() and path.stat().st_size > 0:
            return path.read_text(encoding="utf-8")
        resp = requests.get(f"{CSV_BASE}/{name}.csv", timeout=(3, 5))
        resp.raise_for_status()
        text = resp.content.decode("utf-8")
        path.write_text(text, encoding="utf-8")
        return text

    def load(self) -> None:
        """Populate the species table. Safe to call more than once."""
        with self._lock:
            self._load_species()

    def _load_species(self) -> None:
        if self.species:
            return

        species: dict[int, Species] = {}
        rows = csv.DictReader(io.StringIO(self._fetch_csv("pokemon_species")))
        for row in rows:
            gen = int(row["generation_id"])
            if gen > MAX_GENERATION:
                continue
            sid = int(row["id"])
            parent = row["evolves_from_species_id"]
            species[sid] = Species(
                id=sid,
                identifier=row["identifier"],
                generation=gen,
                evolves_from=int(parent) if parent else None,
                chain_id=int(row["evolution_chain_id"]),
                capture_rate=int(row["capture_rate"]),
                is_legendary=row["is_legendary"] == "1",
                is_mythical=row["is_mythical"] == "1",
            )

        names = csv.DictReader(io.StringIO(self._fetch_csv("pokemon_species_names")))
        for row in names:
            sid = int(row["pokemon_species_id"])
            sp = species.get(sid)
            if sp and row["local_language_id"] in (LANG_EN, LANG_KO):
                sp.names[row["local_language_id"]] = row["name"]

        if not species:
            raise ValueError("Empty species table")
        for sp in species.values():
            if sp.evolves_from is not None:
                parent = species.get(sp.evolves_from)
                if parent:
                    parent.children.append(sp.id)

        self.bases = sorted(
            sid for sid, sp in species.items() if sp.evolves_from is None
        )
        self.species = species

    # ---- evolution -------------------------------------------------

    def evolution_path(self, base_id: int, rng) -> list[int]:
        """Walk one concrete branch of a species' evolution tree.

        Branching lines (Eevee, Tyrogue, Wurmple) pick a single branch at hatch
        time so the companion has a definite future to grow into.
        """
        path = [base_id]
        current = self.species[base_id]
        while current.children:
            nxt = rng.choice(sorted(current.children))
            path.append(nxt)
            current = self.species[nxt]
        return path

    # ---- sprites ---------------------------------------------------

    def sprite_path(self, species_id: int, shiny: bool, *, fetch: bool = True) -> Path | None:
        """Prefer an animated GIF, with a matching static PNG as a fallback."""
        name = f"{species_id}{'-shiny' if shiny else ''}"
        url_name = f"{'shiny/' if shiny else ''}{species_id}"
        sources = (
            (self.sprite_dir / f"{name}.gif", f"{SPRITE_BASE}/{url_name}.gif"),
            (self.sprite_dir / f"{name}.png", f"{POKEMON_SPRITE_BASE}/{url_name}.png"),
        )
        for path, _ in sources:
            bundled = self._bundled_file("sprites", path.name)
            if bundled is not None:
                return bundled
            if _usable_sprite(path):
                return path
        if fetch:
            for path, url in sources:
                if self._download_sprite(path, url):
                    return path
        return None

    def _download_sprite(self, path: Path, url: str) -> bool:
        with self._lock:
            if _usable_sprite(path):
                return True
            tmp = None
            try:
                resp = requests.get(url, timeout=(3, 5))
                resp.raise_for_status()
                if not _valid_sprite(io.BytesIO(resp.content), path.suffix[1:].upper()):
                    return False
                with NamedTemporaryFile(dir=path.parent, suffix=".part", delete=False) as file:
                    tmp = Path(file.name)
                    file.write(resp.content)
                tmp.replace(path)
                return True
            except (OSError, requests.RequestException):
                return False
            finally:
                if tmp is not None:
                    tmp.unlink(missing_ok=True)

    def item_sprite_path(self, item_name: str, *, fetch: bool = True) -> Path | None:
        """Local path to a PokeAPI item sprite (e.g. 'rare-candy')."""
        filename = f"{item_name}.png"
        return self._item_path(filename, f"{ITEM_BASE}/{filename}", fetch=fetch)

    def egg_sprite_path(self, shiny: bool = False, *, fetch: bool = True) -> Path | None:
        """The egg shown before a companion hatches, fetched like any sprite."""
        name = "egg-shiny.png" if shiny else "egg.png"
        url = f"{ITEM_BASE}/lucky-egg.png" if shiny else EGG_URL
        return self._item_path(name, url, fetch=fetch)

    def _item_path(self, filename: str, url: str, *, fetch: bool) -> Path | None:
        bundled = self._bundled_file("items", filename)
        if bundled is not None:
            return bundled
        path = self.item_dir / filename
        if _usable_sprite(path) or (fetch and self._download_sprite(path, url)):
            return path
        return None
