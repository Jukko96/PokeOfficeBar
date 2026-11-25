"""Settings, active desktop time, and companion artwork."""

from __future__ import annotations

import logging
import os
import sys
import threading
from collections import OrderedDict
from dataclasses import asdict, dataclass
from datetime import datetime
from math import ceil
from pathlib import Path
from queue import SimpleQueue
from time import monotonic

from PIL import Image, ImageSequence
from requests import RequestException

from .art import FOG_VISITOR_ID, fog_visitor_frames, item_art
from .game import CandyUseNotice, Game
from .i18n import set_lang, t
from .persistence import atomic_json, read_json
from .pokedata import Pokedex
from .startup import set_startup
from .updates import check_for_update

ROAM_OFF, ROAM_SCREEN, ROAM_TASKBAR = "off", "screen", "taskbar"
WORK_TIMES = {
    "work_start_time": "09:00", "lunch_time": "12:00",
    "work_resume_time": "13:00", "work_end_time": "18:00",
}
MINUTES_PER_DAY = 24 * 60
ITEM_SPRITES = {
    "gift_box": "gift-box", "rare_candy": "rare-candy", "mint": "ability-urge",
    "shiny_charm": "shiny-charm", "soothe_bell": "soothe-bell", "incense": "incense",
}


def normalize_work_time(value: str) -> str | None:
    """Return a 24-hour HH:MM value, or None for invalid input."""
    try:
        return datetime.strptime(value.strip(), "%H:%M").strftime("%H:%M")
    except ValueError:
        return None


def _clock_minutes(value: str) -> int:
    hour, minute = map(int, value.split(":"))
    return 60 * hour + minute


def _fit(src: Image.Image, size: int) -> Image.Image:
    """Letterbox an image into a size x size box. Never crops.

    Fit the longest side to the requested size at every value, preserving the
    aspect ratio. Nearest-neighbour enlargement keeps pixel edges sharp;
    shrinking uses a smooth filter. The same scale applies to every animation
    frame, so changing the size does not change the animation's alignment.
    """
    scale = min(size / src.width, size / src.height)
    w = max(1, round(src.width * scale))
    h = max(1, round(src.height * scale))
    resample = Image.NEAREST if scale >= 1 else Image.LANCZOS
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    resized = src.resize((w, h), resample) if (w, h) != src.size else src
    out.paste(resized, ((size - w) // 2, (size - h) // 2), resized)
    return out


def _brief(exc: BaseException, limit: int = 140) -> str:
    """Collapse an error message into a short label."""
    text = " ".join(str(exc).split()) or type(exc).__name__
    return text if len(text) <= limit else text[: limit - 1] + "…"


def asset_dir() -> Path:
    """Where bundled images live, in a source checkout or inside the exe.

    PyInstaller's one-file build unpacks data files to a temp dir it points at
    with sys._MEIPASS, so the packaged path is not next to this module.
    """
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) / "assets" if base else Path(__file__).resolve().parent / "assets"


_EGG_CACHE: dict[tuple[int, bool], Image.Image] = {}


def egg_image(size: int, shiny: bool = False) -> Image.Image:
    key = (size, shiny)
    if key not in _EGG_CACHE:
        _EGG_CACHE[key] = _draw_egg(size, shiny)
    return _EGG_CACHE[key]


def _draw_egg(size: int, shiny: bool = False) -> Image.Image:
    """Draw the egg used in the app and executable icon."""
    from PIL import ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = size // 6
    d.ellipse(
        [pad, pad // 2, size - pad, size - pad // 2],
        fill=(219, 246, 238) if shiny else (246, 238, 217),
        outline=(77, 155, 142) if shiny else (180, 160, 120),
        width=max(2, size // 32),
    )
    for i in range(3):
        y = size // 2 + i * size // 8
        d.arc([pad + size // 12, y - size // 10, size - pad - size // 12, y + size // 10],
              200, 340, fill=(107, 196, 176) if shiny else (210, 188, 140), width=max(2, size // 40))
    return img


def data_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(root) / "PokeOfficeBar"

def game_data_dir() -> Path:
    """Share the existing Windows office save and sprite cache."""
    return data_dir().with_name("PokeTokenBarWin")


@dataclass
class Config:
    language: str = "ko"            # "ko" or "en"
    floating_pet: bool = True
    start_with_windows: bool = True
    work_timer_enabled: bool = False
    work_start_time: str = WORK_TIMES["work_start_time"]
    lunch_time: str = WORK_TIMES["lunch_time"]
    work_resume_time: str = WORK_TIMES["work_resume_time"]
    work_end_time: str = WORK_TIMES["work_end_time"]
    pet_roam_mode: str = ROAM_OFF
    pet_size: int = 96
    incense_max_visitors: int = 5
    # Where the user dragged the pet. -1 means "pick a default corner"; storing
    # it keeps the pet put across restarts and sidesteps display-scaling maths.
    pet_x: int = -1
    pet_y: int = -1
    # Pin a Pokedex species to the tray icon and floating pet, independently of
    # the companion being raised. 0 follows the companion.
    pinned_species: int = 0
    animate_tray: bool = True

    @classmethod
    def load(cls, path: Path) -> "Config":
        """Read the config, tolerating a BOM, unknown keys, and missing keys.

        A file written by an older version simply lacks the newer fields; the
        dataclass defaults fill them in, and App.__init__ writes the file back
        complete, so upgrading never strands a half-populated config.
        """
        if path.exists():
            try:
                raw = read_json(path)
                if not isinstance(raw, dict):
                    return cls()
                defaults = cls()
                known = {k: v for k, v in raw.items() if k in cls.__annotations__
                         and type(v) is type(getattr(defaults, k))}
                known["pet_size"] = max(48, min(192, known.get("pet_size", defaults.pet_size)))
                known["incense_max_visitors"] = max(1, known.get("incense_max_visitors", defaults.incense_max_visitors))
                has_resume_time = normalize_work_time(known.get("work_resume_time", "")) is not None
                for key, default in WORK_TIMES.items():
                    known[key] = normalize_work_time(known.get(key, default)) or default
                if known.get("language", "ko") not in ("ko", "en"):
                    known["language"] = "ko"
                old_mode = ROAM_SCREEN if raw.get("pet_roams") is True else ROAM_OFF
                mode = known.get("pet_roam_mode", old_mode)
                known["pet_roam_mode"] = mode if mode in (ROAM_SCREEN, ROAM_TASKBAR) else ROAM_OFF
                config = cls(**known)
                if not has_resume_time and not config.valid_work_schedule():
                    lunch = _clock_minutes(config.lunch_time)
                    gap = (_clock_minutes(config.work_end_time) - lunch) % MINUTES_PER_DAY
                    if gap > 1:
                        resume = (lunch + min(60, gap - 1)) % MINUTES_PER_DAY
                        hour, minute = divmod(resume, 60)
                        config.work_resume_time = f"{hour:02}:{minute:02}"
                if not config.valid_work_schedule():
                    for key, default in WORK_TIMES.items():
                        setattr(config, key, default)
                return config
            except (OSError, ValueError, TypeError):
                pass
        return cls()

    def matches_file(self, path: Path) -> bool:
        """True if `path` already holds exactly these settings."""
        try:
            return read_json(path) == asdict(self)
        except (OSError, ValueError):
            return False

    def save(self, path: Path) -> None:
        atomic_json(path, asdict(self))

    def _work_offsets(self) -> tuple[int, int, int]:
        start = _clock_minutes(self.work_start_time)
        lunch = (_clock_minutes(self.lunch_time) - start) % MINUTES_PER_DAY
        resume = (_clock_minutes(self.work_resume_time) - start) % MINUTES_PER_DAY
        end = (_clock_minutes(self.work_end_time) - start) % MINUTES_PER_DAY
        return lunch, resume, end

    def valid_work_schedule(self) -> bool:
        lunch, resume, end = self._work_offsets()
        return 0 < lunch < resume < end

    def work_countdown_text(self, now: datetime) -> str:
        if not self.work_timer_enabled:
            return ""
        local_seconds = (now.hour * 60 + now.minute) * 60 + now.second + now.microsecond / 1_000_000
        start_seconds = _clock_minutes(self.work_start_time) * 60
        elapsed = (local_seconds - start_seconds) % (MINUTES_PER_DAY * 60)
        lunch, resume, end = self._work_offsets()
        phases = (("lunch", lunch), ("resume", resume), ("end", end))
        for phase, minutes in phases:
            remaining = ceil(minutes * 60 - elapsed)
            if remaining > 0:
                hours, remainder = divmod(remaining, 3600)
                minutes, seconds = divmod(remainder, 60)
                return t(f"work_timer.{phase}", time=f"{hours:02}:{minutes:02}:{seconds:02}")
        if elapsed < end * 60 + 60:
            return t("work_timer.finished")
        return ""


class App:
    """Owns local data, the game, and the presentation caches."""

    def __init__(self) -> None:
        self.dir = data_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.dir / "config.json"
        shared = game_data_dir()
        initial_config = self.config_path if self.config_path.exists() else shared / "config.json"
        self.config = Config.load(initial_config)
        if not self.config.matches_file(self.config_path):
            # First run, or a file from an older version missing newer keys.
            self.config.save(self.config_path)
        set_lang(self.config.language)

        self.dex = Pokedex(shared / "cache")
        self.game = Game(self.dex, shared / "office-save.json")

        self.ready = False
        self.office_paused = False
        self._office_last_tick: float | None = None
        self._office_was_unlocked = False
        self.error: str | None = None
        self.startup_error = False
        self.version_checking = True
        self.version_check_failed = False
        self.available_version: str | None = None
        self.listeners: list = []
        self._frame_cache = OrderedDict()
        self._still_cache = OrderedDict()
        self._item_cache = OrderedDict()
        self.egg_art_revision = 0
        self._image_jobs = SimpleQueue()
        self._pending_images: set[tuple] = set()
        self._image_retry_after: dict[tuple, float] = {}
        self._image_lock = threading.Lock()
        self._image_stop = threading.Event()
        self._image_worker: threading.Thread | None = None

    @property
    def game_total(self) -> int:
        return self.game.office_points

    def tick_office(self, now: float, unlocked: bool) -> bool:
        """Count short, unlocked timer intervals and discard lock/suspend gaps."""
        previous = self._office_last_tick
        was_unlocked = self._office_was_unlocked
        self._office_last_tick = now
        self._office_was_unlocked = unlocked
        self.office_paused = not unlocked
        if not self.ready or previous is None:
            return False
        seconds = now - previous
        if not (unlocked and was_unlocked and 0 < seconds <= 2.5):
            return False
        points = self.game.office_points
        pending = self.game.pending_gift
        events = self.game.advance_office_time(seconds)
        recovered = self.error is not None
        self.error = None
        if self.game.office_points == points and self.game.pending_gift is pending and not events and not recovered:
            return False
        self.request_refresh(events)
        return True

    def use_candy(self) -> str | None:
        result = self.game.use_candy()
        if isinstance(result, CandyUseNotice):
            self.request_refresh([result])
        return result

    def claim_gift(self) -> None:
        try:
            message = self.game.claim_gift()
        except OSError:
            logging.exception("Gift claim could not be saved")
            self._notify([t("gift.retry")])
            return
        if message:
            self._notify([message])

    def claim_visitor_gift(self, identity: tuple[int, bool]) -> bool:
        try:
            message = self.game.claim_visitor_gift(identity)
        except OSError:
            logging.exception("Visitor gift claim could not be saved")
            self._notify([t("gift.retry")])
            return False
        if not message:
            return False
        self._notify([message])
        return True

    def discover_fog_visitor(self) -> bool:
        try:
            message = self.game.reward_fog_visitor()
        except OSError:
            logging.exception("Disguised visitor reward could not be saved")
            self.request_refresh([t("save.retry")])
            return False
        if not message:
            return False
        self.request_refresh([message])
        return True

    def start(self) -> None:
        if self.dex.has_local_tables():
            self._load_profile()
        else:
            self._queue_image(("catalog",))
        self._image_worker = threading.Thread(target=self._fetch_images,
                                              name="pokeofficebar-assets", daemon=True)
        self._image_worker.start()
        threading.Thread(target=self._check_release, name="pokeofficebar-version", daemon=True).start()

    def _check_release(self) -> None:
        try:
            self.available_version = check_for_update()
        except (RequestException, ValueError) as exc:
            self.version_check_failed = True
            logging.info("Could not check latest version: %s", _brief(exc))
        finally:
            self.version_checking = False
        events = [t("updates.available", version=self.available_version)] if self.available_version else []
        self._notify(events)

    def _load_profile(self) -> bool:
        try:
            self.dex.load()
            with self.game.lock:
                if self._image_stop.is_set():
                    return False
                self.game.load()
                self.error = None
                self.ready = True
        except Exception as exc:
            logging.exception("Office profile could not load")
            self.error = t("err.refresh", err=_brief(exc))
        self._notify()
        return self.ready

    def _queue_image(self, key: tuple) -> None:
        with self._image_lock:
            if self._image_stop.is_set() or key in self._pending_images:
                return
            if monotonic() < self._image_retry_after.get(key, 0):
                return
            self._pending_images.add(key)
            self._image_jobs.put(key)

    def _fetch_images(self) -> None:
        while not self._image_stop.is_set():
            key = self._image_jobs.get()
            if key is None or self._image_stop.is_set():
                return
            kind, *args = key
            found = False
            try:
                if kind == "catalog":
                    found = self._load_profile()
                elif kind == "sprite":
                    found = self.dex.sprite_path(*args) is not None
                elif kind == "egg":
                    found = self.dex.egg_sprite_path(*args) is not None
                    if found:
                        self.egg_art_revision += 1
                else:
                    found = self.dex.item_sprite_path(*args) is not None
            except (OSError, ValueError):
                logging.exception("Could not load artwork for %r", key)
            finally:
                with self._image_lock:
                    self._pending_images.discard(key)
                    if found:
                        self._image_retry_after.pop(key, None)
                    else:
                        self._image_retry_after[key] = monotonic() + (5 if kind == "catalog" else 60)
            if found and kind != "catalog":
                self._notify()

    def sync_windows_startup(self) -> None:
        try:
            set_startup(self.config.start_with_windows)
        except OSError:
            self.startup_error = True
            logging.warning("Windows startup setting could not be applied", exc_info=True)
        else:
            self.startup_error = False

    def stop(self) -> None:
        self._image_stop.set()
        self._image_jobs.put(None)
        if self._image_worker is not None:
            self._image_worker.join(timeout=.2)
        if not self.game.initialized:
            return
        if self.game.incense_status()[0]:
            self.game.toggle_incense()
        self.game.save()

    def subscribe(self, fn) -> None:
        self.listeners.append(fn)

    def request_refresh(self, events: list[str] | None = None) -> None:
        if not self.ready and self.error and not events:
            self._queue_image(("catalog",))
        self._notify(events)

    def _notify(self, events: list[str] | None = None) -> None:
        if self._image_stop.is_set():
            return
        for fn in list(self.listeners):
            try:
                fn(events or [])
            except Exception:
                pass

    def display_sprite(self) -> tuple[int | None, bool]:
        """What the tray icon and floating pet should show.

        A pinned species wins over the companion, so the glanceable surfaces
        stop changing at every hatch and evolution. Home still shows the real
        companion and its progress.
        """
        with self.game.lock:
            pinned = self.config.pinned_species
            if pinned in self.dex.species:
                rec = self.game.pokedex.get(pinned)
                if rec:
                    return pinned, bool(rec.get("shiny"))
            c = self.game.companion
            return c.species_id, c.shiny

    # ---- sprites ---------------------------------------------------

    def frames(self, species_id: int, shiny: bool, size: int) -> list[Image.Image]:
        """Animated sprite frames, scaled with nearest-neighbour to stay crisp."""
        key = (species_id, shiny)
        if species_id != FOG_VISITOR_ID and species_id not in self.dex.species:
            return []
        if key not in self._frame_cache:
            if species_id == FOG_VISITOR_ID:
                raw = fog_visitor_frames()
            else:
                path = self.dex.sprite_path(species_id, shiny, fetch=False)
                if path is None:
                    self._queue_image(("sprite", species_id, shiny))
                    return []
                try:
                    with Image.open(path) as image:
                        raw = [frame.convert("RGBA") for frame in ImageSequence.Iterator(image)]
                except (OSError, ValueError):
                    logging.warning("Invalid sprite: %s", path)
                    return []
                bounds = [box for frame in raw if (box := frame.getbbox()) is not None]
                if bounds:
                    box = (min(b[0] for b in bounds), min(b[1] for b in bounds),
                           max(b[2] for b in bounds), max(b[3] for b in bounds))
                    raw = [frame.crop(box) for frame in raw]
            self._frame_cache[key] = raw
            if len(self._frame_cache) > 32:
                self._frame_cache.popitem(last=False)
        self._frame_cache.move_to_end(key)
        raw = self._frame_cache[key]
        if not raw:
            return []
        return [_fit(f, size) for f in raw]

    def egg_frames(self, size: int, shiny: bool = False) -> list[Image.Image]:
        """Use the original egg sprite and retain a fallback while downloading."""
        path = self.dex.egg_sprite_path(shiny, fetch=False)
        if path is None:
            self._queue_image(("egg", shiny))
            return [egg_image(size, shiny=shiny)]
        cache_key = ("egg_asset", shiny, size)
        if cache_key not in self._item_cache:
            with Image.open(path) as source:
                image = source.convert("RGBA")
            bounds = image.getbbox()
            self._cache_item(cache_key, _fit(image.crop(bounds) if bounds else image, size))
        return [self._item_cache[cache_key]]

    def still(self, species_id: int, shiny: bool, size: int) -> Image.Image | None:
        """One static frame, for grids where 24 animations would be wasteful."""
        key = (species_id, shiny, size)
        if key in self._still_cache:
            self._still_cache.move_to_end(key)
            return self._still_cache[key]
        frames = self.frames(species_id, shiny, size)
        img = frames[0] if frames else None
        if img is not None:
            self._still_cache[key] = img
            while len(self._still_cache) > 256:
                self._still_cache.popitem(last=False)
        return img

    def item_image(self, item_key: str, size: int) -> Image.Image | None:
        if item_key.startswith("egg_"):
            return self.egg_frames(size)[0]
        cache_key = (item_key, size)
        if cache_key in self._item_cache:
            self._item_cache.move_to_end(cache_key)
            return self._item_cache[cache_key]
        name = ITEM_SPRITES.get(item_key)
        path = self.dex.item_sprite_path(name, fetch=False) if name else None
        if path is None:
            if name and item_key != "incense":
                self._queue_image(("item", name))
            fallback = item_art(item_key)
            return _fit(fallback, size) if fallback is not None else None
        with Image.open(path) as source:
            image = _fit(source.convert("RGBA"), size)
        return self._cache_item(cache_key, image)

    def _cache_item(self, key: tuple, image: Image.Image) -> Image.Image:
        self._item_cache[key] = image
        if len(self._item_cache) > 128:
            self._item_cache.popitem(last=False)
        return image
