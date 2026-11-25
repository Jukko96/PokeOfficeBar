"""Eggs hatch, companions grow and graduate, and points accrue with active time."""

from __future__ import annotations

import json
import random
import threading
from copy import deepcopy
from functools import wraps
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from time import time

from .pokedata import Pokedex
from .i18n import lang, nature as tr_nature, rarity as tr_rarity, t
from .persistence import atomic_json, read_json


def _transaction(method):
    """Serialize mutations and commit nested operations as one disk write."""
    @wraps(method)
    def run(self, *args, **kwargs):
        with self.lock:
            outer = self._transaction_depth == 0
            if outer:
                runtime = {"dex", "path", "rng", "lock", "_transaction_depth", "_save_pending"}
                before = deepcopy({key: value for key, value in vars(self).items()
                                   if key not in runtime and not key.startswith("_") and not callable(value)})
                random_state = self.rng.getstate()
                self._save_pending = False
            self._transaction_depth += 1
            try:
                result = method(self, *args, **kwargs)
                if outer and self._save_pending:
                    self._write_save()
                return result
            except Exception:
                if outer:
                    vars(self).update(before)
                    self.rng.setstate(random_state)
                raise
            finally:
                self._transaction_depth -= 1
                if outer:
                    self._save_pending = False
    return run

NATURES = [
    "Hardy", "Lonely", "Brave", "Adamant", "Naughty",
    "Bold", "Docile", "Relaxed", "Impish", "Lax",
    "Timid", "Hasty", "Serious", "Jolly", "Naive",
    "Modest", "Mild", "Quiet", "Bashful", "Rash",
    "Calm", "Gentle", "Sassy", "Careful", "Quirky",
]

# Fraction of the graduation total at which each evolution fires, by line length.
EVOLVE_FRACTIONS = {1: [], 2: [0.40], 3: [0.25, 0.60]}

BASE_SHINY_ODDS = 256          # 1 in N
SHINY_CHARM_FACTOR = 0.6       # charm multiplies the denominator
MAX_SHINY_CHARMS = 9
MAX_SOOTHE_BELLS = 3
MAX_SHINY_CHANCE = 0.30
INCENSE_SECONDS = 600

OFFICE_POINT_SECONDS = 60
GIFT_WAIT_RANGE = (2400, 5400)
GIFT_SCHEDULE_VERSION = 2
VISITOR_GIFT_CHANCE = 0.05
FOG_VISITOR_POINTS = 3
GIFT_ITEM_WEIGHTS = {"points": 82, "mint": 12, "rare_candy": 3, "incense": 3}
OFFICE_HATCH_POINTS = 20
OFFICE_GRADUATE_POINTS = 76
OFFICE_CANDY_POINTS = 20
BERRY_GROW_SECONDS = 2 * 60 * 60
BERRY_CANDY_CHANCE = 0.05
BERRY_POINT_MULTIPLIER = 10
BERRY_POT_COUNT = 4
BERRY_POT_PRICE = 500
OFFICE_SHOP_PRICES = {
    "rare_candy": 16,
    "mint": 10,
    "incense": 20,
    "shiny_charm": 480,
    "soothe_bell": 480,
    "egg_plain": 24,
    "egg_uncommon": 60,
    "egg_rare": 160,
}
BAG_ITEM_FIELDS = {
    "rare_candy": "candies",
    "mint": "mints",
    "incense": "incense",
    "shiny_charm": "shiny_charms",
    "soothe_bell": "soothe_bell",
}

# Minimum rarity guaranteed by each graded egg.
EGG_FLOORS = {
    "egg_plain": None,
    "egg_uncommon": ("Uncommon", "Rare", "Very Rare", "Legendary"),
    "egg_rare": ("Rare", "Very Rare", "Legendary"),
}

RARITY_ORDER = ["Common", "Uncommon", "Rare", "Very Rare", "Legendary"]
EXPEDITION_COOLDOWN_SECONDS = 24 * 60 * 60
EXPEDITION_HISTORY_LIMIT = 10


@dataclass(frozen=True)
class Destination:
    rarity: str
    minutes: int
    points: int
    shiny_bonus: int

    def reward_for(self, shiny: bool) -> int:
        return self.points + (self.shiny_bonus if shiny else 0)


EXPEDITION_DESTINATIONS = {
    "meadow": Destination("Common", 60, 30, 20),
    "forest": Destination("Uncommon", 90, 50, 30),
    "lake": Destination("Rare", 120, 80, 40),
    "cave": Destination("Very Rare", 180, 120, 60),
    "summit": Destination("Legendary", 240, 160, 80),
}


@dataclass(frozen=True)
class Expedition:
    species_id: int
    shiny: bool
    finish_at: float


@dataclass(frozen=True)
class ExpeditionReturn:
    species_id: int
    shiny: bool
    points: int
    returned_at: float | None = None
    claimed: bool = True


class ExpeditionReturnNotice(str):
    """A return message that should stay visible in the desktop pet alert."""


class CandyUseNotice(str):
    """A committed candy use and any growth milestones it triggered."""


class SaveUnreadable(Exception):
    """The save exists but could not be parsed.

    Raised rather than handled quietly: starting a fresh egg here would erase a
    player's collection to work around what is usually a transient problem.
    """


@dataclass
class Companion:
    """The companion or egg currently being raised."""

    hatched: bool = False
    path: list[int] = field(default_factory=list)   # chosen evolution branch
    stage: int = 0                                  # index into path
    shiny: bool = False
    nature: str = "Hardy"
    rarity: str = "Common"
    anchor: int = 0            # accrued points when this phase started
    bonus: int = 0             # growth granted by Rare Candy
    born_at: str = ""
    egg_floor: list[str] | None = None
    shiny_rolled: bool = False

    @property
    def species_id(self) -> int | None:
        return self.path[self.stage] if self.hatched and self.path else None

    def to_dict(self) -> dict:
        return {
            "hatched": self.hatched, "path": self.path, "stage": self.stage,
            "shiny": self.shiny, "nature": self.nature, "rarity": self.rarity,
            "anchor": self.anchor, "bonus": self.bonus, "born_at": self.born_at,
            "egg_floor": self.egg_floor,
            "shiny_rolled": self.shiny_rolled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Companion":
        return cls(**{k: d.get(k, getattr(cls(), k)) for k in cls().to_dict()})


@dataclass
class BerryPot:
    unlocked: bool
    planted_at: float | None = None


class Game:
    def __init__(self, dex: Pokedex, path: Path) -> None:
        self.lock = threading.RLock()
        self._transaction_depth = 0
        self._save_pending = False
        self.dex = dex
        self.path = path
        self.companion = Companion()
        self.pokedex: dict[int, dict] = {}     # species id -> {"shiny": bool, "count": int}
        self.catch_log: list[dict] = []
        self.graduated: dict[bool, set[int]] = {False: set(), True: set()}
        self.candies = 0
        self.mints = 0
        self.incense = 0
        self.incense_bank = 0.0
        self.incense_until = 0.0
        self.shiny_charms = 0
        self.spent = 0
        self.currency_anchor = 0
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.initialized = False
        self.rng = random.Random()
        self.office_points = 0
        self.office_seconds = 0.0
        self.office_shop_bonus = 0
        self.soothe_bell = 0
        self.gift_wait_seconds = self._next_gift_wait()
        self.gift_elapsed_seconds = 0.0
        self.pending_gift: dict | None = None
        self.visitor_gift: tuple[tuple[int, bool], dict] | None = None
        self.berry_pots = [BerryPot(unlocked=slot == 0) for slot in range(BERRY_POT_COUNT)]
        self.expeditions: dict[str, Expedition] = {}
        self.expedition_returns: dict[str, ExpeditionReturn] = {}
        self.expedition_history: list[tuple[str, ExpeditionReturn]] = []
        self.expedition_cooldowns: dict[int, float] = {}

    # ---- persistence -----------------------------------------------

    @_transaction
    def load(self) -> None:
        data = {}
        if self.path.exists() and self.path.stat().st_size > 0:
            try:
                data = read_json(self.path)
            except (OSError, ValueError) as exc:
                # Keep the file exactly as it is so it can be recovered by hand.
                raise SaveUnreadable(str(exc)) from exc
            if not isinstance(data, dict):
                raise SaveUnreadable("save is not a JSON object")

        if data:
            self.companion = Companion.from_dict(data.get("companion", {}))
            self.pokedex = {int(k): v for k, v in data.get("pokedex", {}).items()}
            self.catch_log = data.get("catch_log", [])
            graduates = data.get("graduated", {})
            self.graduated = {
                False: {int(sid) for sid in graduates.get("normal", [])},
                True: {int(sid) for sid in graduates.get("shiny", [])},
            }
            # Keep the permanent ledger separate from the 300-entry history.
            for record in self.catch_log:
                if record.get("final"):
                    self.graduated[bool(record.get("shiny"))].add(int(record["final"]))
            self.candies = data.get("candies", 0)
            self.mints = data.get("mints", 0)
            incense = data.get("incense", 0)
            self.incense = max(0, incense) if type(incense) is int else 0
            self.incense_bank = 0.0
            self.incense_until = 0.0
            for key in ("incense_bank", "incense_until"):
                value = data.get(key, 0)
                if type(value) in (float, int) and 0 <= value <= 1e12 and isfinite(value):
                    setattr(self, key, value)
            self.shiny_charms = min(MAX_SHINY_CHARMS, max(0, int(data.get("shiny_charms", 0))))
            self.spent = data.get("spent", 0)
            self.currency_anchor = data.get("currency_anchor", 0)
            self.started_at = data.get("started_at") or self.started_at
            self.office_points = max(0, int(data.get("office_points", 0)))
            self.office_seconds = max(0.0, min(OFFICE_POINT_SECONDS - 0.001, float(data.get("office_seconds", 0))))
            self._load_berry_pots(data)
            self._load_expeditions(data)
            self.office_shop_bonus = max(0, int(data.get("office_shop_bonus", 0)))
            self.soothe_bell = min(MAX_SOOTHE_BELLS, max(0, int(data.get("soothe_bell", 0))))
            self.gift_wait_seconds = float(data.get("gift_wait_seconds", self.gift_wait_seconds))
            self.gift_elapsed_seconds = max(0.0, float(data.get("gift_elapsed_seconds", 0)))
            gift = data.get("pending_gift")
            self.pending_gift = None
            gift_item = gift.get("item") if isinstance(gift, dict) else None
            if (isinstance(gift_item, str) and gift_item in GIFT_ITEM_WEIGHTS
                    and type(gift.get("amount")) is int and 1 <= gift["amount"] <= 3):
                self.pending_gift = gift
            self.initialized = True
            migrated = ("graduated" not in data
                        or "berry_pots" not in data
                        or type(data.get("soothe_bell", 0)) is bool)
            if data.get("gift_schedule_version") != GIFT_SCHEDULE_VERSION:
                progress = min(1.0, self.gift_elapsed_seconds / max(1, self.gift_wait_seconds))
                self.gift_wait_seconds = self._next_gift_wait()
                self.gift_elapsed_seconds = self.gift_wait_seconds * progress
                migrated = True
            if not self.companion.hatched and not self.companion.shiny_rolled:
                self._roll_egg_shiny(self.companion)
                migrated = True
            if migrated:
                self.save()
        else:
            # First run: start a fresh egg and an empty wallet from this moment.
            self.companion = self._new_egg(0)
            self.initialized = True
            self.save()

    def _roll_egg_shiny(self, egg: Companion) -> None:
        if not egg.shiny_rolled:
            normal = bool(self._eligible_bases(False, egg.egg_floor))
            shiny = bool(self._eligible_bases(True, egg.egg_floor))
            if not normal and shiny:
                egg.shiny = True
            elif normal and not shiny:
                egg.shiny = False
            else:
                egg.shiny = egg.shiny or self.rng.random() < 1 / self.shiny_odds()
            egg.shiny_rolled = True

    def _new_egg(self, total_points: int, floor=None) -> Companion:
        egg = Companion(anchor=total_points, egg_floor=list(floor) if floor else None)
        self._roll_egg_shiny(egg)
        return egg

    def _next_gift_wait(self) -> float:
        seconds = self.rng.uniform(*GIFT_WAIT_RANGE)
        return seconds / (2 ** self.soothe_bell)

    @property
    def gift_wait_range(self) -> tuple[float, float]:
        return tuple(seconds / (2 ** self.soothe_bell) for seconds in GIFT_WAIT_RANGE)

    def save(self) -> None:
        with self.lock:
            if self._transaction_depth:
                self._save_pending = True
            else:
                self._write_save()

    def _write_save(self) -> None:
        payload = {
            "companion": self.companion.to_dict(),
            "pokedex": self.pokedex,
            "catch_log": self.catch_log,
            "graduated": {"normal": sorted(self.graduated[False]),
                          "shiny": sorted(self.graduated[True])},
            "candies": self.candies,
            "mints": self.mints,
            "incense": self.incense,
            "incense_bank": self.incense_bank,
            "incense_until": self.incense_until,
            "shiny_charms": self.shiny_charms,
            "spent": self.spent,
            "currency_anchor": self.currency_anchor,
            "started_at": self.started_at,
            "last_lifetime_tokens": self.office_points,
        }
        payload.update(office_points=self.office_points, office_seconds=self.office_seconds,
                       office_shop_bonus=self.office_shop_bonus,
                       berry_pots=[{"unlocked": pot.unlocked, "planted_at": pot.planted_at}
                                   for pot in self.berry_pots],
                       expeditions={key: asdict(trip) for key, trip in self.expeditions.items()},
                       expedition_returns={key: asdict(report)
                                           for key, report in self.expedition_returns.items()},
                       expedition_history=[{"destination": key, **asdict(report)}
                                           for key, report in self.expedition_history],
                       expedition_cooldowns=self.expedition_cooldowns,
                       gift_wait_seconds=self.gift_wait_seconds,
                       gift_elapsed_seconds=self.gift_elapsed_seconds,
                       pending_gift=self.pending_gift,
                       soothe_bell=self.soothe_bell,
                       gift_schedule_version=GIFT_SCHEDULE_VERSION)
        atomic_json(self.path, payload)

    # ---- derived numbers -------------------------------------------

    def graduate_total(self) -> int:
        return OFFICE_GRADUATE_POINTS

    def progress(self, total_points: int) -> int:
        return max(0, total_points - self.companion.anchor) + self.companion.bonus

    def goal(self) -> int:
        """Points needed to reach the next milestone (hatch, evolve, graduate)."""
        c = self.companion
        if not c.hatched:
            return OFFICE_HATCH_POINTS
        total = self.graduate_total()
        fractions = EVOLVE_FRACTIONS.get(len(c.path), [])
        if c.stage < len(fractions):
            value = total * fractions[c.stage]
            return round(value)
        return total

    @property
    def shop_prices(self) -> dict[str, int]:
        return OFFICE_SHOP_PRICES

    def _available_paths(self, base: int, shiny: bool) -> list[list[int]]:
        def walk(sid, prefix):
            path = prefix + [sid]
            children = self.dex.species[sid].children
            if not children:
                if sid not in self.graduated[shiny]:
                    yield path
            else:
                for child in sorted(children):
                    yield from walk(child, path)
        return list(walk(base, []))

    def _eligible_bases(self, shiny: bool, floor=None) -> list[int]:
        return [sid for sid in self.dex.bases
                if (not floor or self.dex.species[sid].rarity in floor)
                and self._available_paths(sid, shiny)]

    @property
    def collection_complete(self) -> bool:
        return bool(self.dex.bases) and not (self._eligible_bases(False)
                                            or self._eligible_bases(True))

    def can_buy_egg(self, item: str) -> bool:
        floor = EGG_FLOORS[item]
        return bool(self._eligible_bases(False, floor) or self._eligible_bases(True, floor))

    @property
    def _office_active_seconds(self) -> float:
        return self.office_points * OFFICE_POINT_SECONDS + self.office_seconds

    def _load_berry_pots(self, data: dict) -> None:
        saved = data.get("berry_pots")
        if not isinstance(saved, list):
            saved = [{"planted_at": data.get("berry_planted_at")}]
        for slot in range(BERRY_POT_COUNT):
            record = saved[slot] if slot < len(saved) and isinstance(saved[slot], dict) else {}
            unlocked = slot == 0 or record.get("unlocked") is True
            planted = record.get("planted_at")
            planted_at = None
            if unlocked and type(planted) in (float, int) and 0 <= planted < float("inf"):
                planted_at = min(planted, self._office_active_seconds)
            self.berry_pots[slot] = BerryPot(unlocked, planted_at)

    def _berry_pot(self, slot: int) -> BerryPot | None:
        if self.initialized and type(slot) is int and 0 <= slot < BERRY_POT_COUNT:
            return self.berry_pots[slot]
        return None

    def berry_growth(self, slot: int) -> float | None:
        pot = self._berry_pot(slot)
        if pot is None or pot.planted_at is None:
            return None
        elapsed = self._office_active_seconds - pot.planted_at
        return min(1.0, max(0.0, elapsed / BERRY_GROW_SECONDS))

    @_transaction
    def unlock_berry_pot(self, slot: int) -> str | None:
        pot = self._berry_pot(slot)
        if pot is None or pot.unlocked or self.currency(self.office_points) < BERRY_POT_PRICE:
            return None
        pot.unlocked = True
        self.spent += BERRY_POT_PRICE
        self.save()
        return t("berry.unlocked", number=slot + 1)

    @_transaction
    def plant_berry(self, slot: int) -> str | None:
        pot = self._berry_pot(slot)
        if pot is None or not pot.unlocked or pot.planted_at is not None:
            return None
        pot.planted_at = self._office_active_seconds
        self.save()
        return t("berry.planted")

    @_transaction
    def plant_all_berries(self) -> str | None:
        planted = sum(self.plant_berry(slot) is not None for slot in range(BERRY_POT_COUNT))
        if planted:
            return t("berry.plant_result", count=planted)
        return None

    @_transaction
    def harvest_berry(self, slot: int) -> str | None:
        pot = self._berry_pot(slot)
        if pot is None or not pot.unlocked or self.berry_growth(slot) != 1.0:
            return None
        points, candies = self._harvest_berry(pot)
        self.save()
        name = t("gift.points" if points else "item.rare_candy")
        return t("berry.harvested", item=name, amount=points or candies)

    def _harvest_berry(self, pot: BerryPot) -> tuple[int, int]:
        pot.planted_at = None
        if self.rng.random() < BERRY_CANDY_CHANCE:
            self.candies += 1
            return 0, 1
        points = self.rng.randint(2, 4) * BERRY_POINT_MULTIPLIER
        self.office_shop_bonus += points
        return points, 0

    @_transaction
    def harvest_ripe_berries(self) -> str | None:
        if not self.initialized:
            return None
        ripe = [pot for slot, pot in enumerate(self.berry_pots)
                if pot.unlocked and self.berry_growth(slot) == 1.0]
        if not ripe:
            return None
        points = candies = 0
        for pot in ripe:
            additional_points, additional_candies = self._harvest_berry(pot)
            points += additional_points
            candies += additional_candies
        self.save()
        rewards = []
        if points:
            rewards.append(t("berry.batch_points", points=points))
        if candies:
            rewards.append(t("berry.batch_candy", candies=candies))
        return t("berry.batch_result", count=len(ripe), rewards=" · ".join(rewards))

    def _load_expeditions(self, data: dict) -> None:
        self.expeditions = {}
        self.expedition_returns = {}
        self.expedition_history = []
        self.expedition_cooldowns = {}
        stored_cooldowns = data.get("expedition_cooldowns")
        now = time()
        if isinstance(stored_cooldowns, dict):
            self.expedition_cooldowns = {
                sid: until for sid in self.graduated[False] | self.graduated[True]
                if sid in self.dex.species and type(until := stored_cooldowns.get(str(sid))) in (int, float)
                and now < until < float("inf")
            }
        busy = set()
        trips = data.get("expeditions")
        returns = data.get("expedition_returns")
        for key in EXPEDITION_DESTINATIONS:
            record = trips.get(key) if isinstance(trips, dict) else None
            identity = self._saved_expedition_identity(record)
            if identity is not None and identity not in busy:
                finish = record.get("finish_at")
                if type(finish) in (int, float) and 0 <= finish < float("inf"):
                    self.expeditions[key] = Expedition(*identity, finish)
                    busy.add(identity)
            report = self._saved_expedition_return(key, returns.get(key) if isinstance(returns, dict) else None)
            if report is not None:
                self.expedition_returns[key] = report

        history = data.get("expedition_history")
        if not isinstance(history, list):
            # Older releases only kept the last result at each destination.
            self.expedition_history = list(self.expedition_returns.items())
            return
        for record in history:
            key = record.get("destination") if isinstance(record, dict) else None
            if not isinstance(key, str) or key not in EXPEDITION_DESTINATIONS:
                continue
            report = self._saved_expedition_return(key, record)
            if report is not None:
                self.expedition_history.append((key, report))
                if len(self.expedition_history) == EXPEDITION_HISTORY_LIMIT:
                    break

    def _saved_expedition_identity(self, record) -> tuple[int, bool] | None:
        if not isinstance(record, dict):
            return None
        sid, shiny = record.get("species_id"), record.get("shiny")
        if (type(sid) is int and type(shiny) is bool
                and sid in self.graduated[shiny] and sid in self.dex.species):
            return sid, shiny
        return None

    def _saved_expedition_return(self, key: str, record) -> ExpeditionReturn | None:
        identity = self._saved_expedition_identity(record)
        if identity is None:
            return None
        points = record.get("points")
        if type(points) is not int or points <= 0:
            return None
        returned_at = record.get("returned_at")
        if type(returned_at) not in (int, float) or not 0 <= returned_at < float("inf"):
            returned_at = None
        claimed = record.get("claimed") is not False
        if not claimed:
            points = EXPEDITION_DESTINATIONS[key].reward_for(identity[1])
        return ExpeditionReturn(*identity, points, returned_at, claimed=claimed)

    def expedition_candidates(self) -> dict[tuple[int, bool], str]:
        """Map each available graduate to its original growth rarity."""
        blocked = {trip.species_id for trip in self.expeditions.values()} | self.expedition_resting_species()
        records = {(record.get("final"), bool(record.get("shiny"))): record.get("rarity")
                   for record in reversed(self.catch_log) if type(record.get("final")) is int}
        candidates = {}
        for shiny, ids in self.graduated.items():
            for sid in ids:
                identity = (sid, shiny)
                if sid in blocked or sid not in self.dex.species:
                    continue
                grade = records.get(identity)
                if grade not in RARITY_ORDER:
                    base = self.dex.species[sid]
                    while base.evolves_from in self.dex.species:
                        base = self.dex.species[base.evolves_from]
                    grade = base.rarity
                candidates[identity] = grade
        return candidates

    def expedition_resting_species(self) -> set[int]:
        now = time()
        return {sid for sid, until in self.expedition_cooldowns.items() if until > now}

    def expedition_rest_remaining(self, sid: int) -> float:
        return max(0.0, self.expedition_cooldowns.get(sid, 0) - time())

    def expedition_remaining(self, key: str) -> float:
        return max(0.0, self.expeditions[key].finish_at - self._office_active_seconds)

    def expedition_reward_pending(self, key: str) -> bool:
        report = self.expedition_returns.get(key)
        return report is not None and not report.claimed

    @_transaction
    def start_expedition(self, key: str, sid: int, shiny: bool) -> bool:
        destination = EXPEDITION_DESTINATIONS.get(key)
        if not self.initialized or destination is None or key in self.expeditions:
            return False
        if self.expedition_reward_pending(key):
            return False
        if type(sid) is not int or type(shiny) is not bool:
            return False
        grade = self.expedition_candidates().get((sid, shiny))
        if grade is None or RARITY_ORDER.index(grade) < RARITY_ORDER.index(destination.rarity):
            return False
        finish_at = self._office_active_seconds + destination.minutes * 60
        self.expeditions[key] = Expedition(sid, shiny, finish_at)
        self.save()
        return True

    @_transaction
    def claim_expedition_reward(self, key: str) -> str | None:
        if not self.expedition_reward_pending(key):
            return None
        report = self.expedition_returns[key]
        claimed = replace(report, claimed=True)
        self.expedition_returns[key] = claimed
        for index, entry in enumerate(self.expedition_history):
            if entry == (key, report):
                self.expedition_history[index] = (key, claimed)
                break
        self.office_shop_bonus += report.points
        self.save()
        return t("expedition.reward_claimed", points=report.points)

    def _finish_expeditions(self) -> list[str]:
        messages = []
        now = time()
        for key, trip in sorted(self.expeditions.items(), key=lambda entry: entry[1].finish_at):
            if self.expedition_remaining(key) > 0:
                continue
            points = EXPEDITION_DESTINATIONS[key].reward_for(trip.shiny)
            report = ExpeditionReturn(trip.species_id, trip.shiny, points, returned_at=now, claimed=False)
            self.expedition_returns[key] = report
            self.expedition_history.insert(0, (key, report))
            self.expedition_cooldowns[trip.species_id] = max(
                now + EXPEDITION_COOLDOWN_SECONDS, self.expedition_cooldowns.get(trip.species_id, 0),
            )
            del self.expeditions[key]
            name = self.dex.species[trip.species_id].name(lang())
            if trip.shiny:
                name = t("expedition.shiny_name", name=name)
            messages.append(ExpeditionReturnNotice(t("expedition.return", name=name, points=points)))
        if messages:
            del self.expedition_history[EXPEDITION_HISTORY_LIMIT:]
            self.expedition_cooldowns = {sid: until for sid, until in self.expedition_cooldowns.items()
                                         if until > now}
        return messages

    @_transaction
    def advance_office_time(self, seconds: float) -> list[str]:
        """Accumulate active session time and persist each point award."""
        if not self.initialized or seconds <= 0:
            return []
        gift_found = False
        if self.pending_gift is None and self.visitor_gift is None:
            self.gift_elapsed_seconds += seconds
            if self.gift_elapsed_seconds >= self.gift_wait_seconds:
                self.pending_gift = self._roll_gift()
                gift_found = True
        previous_time = self._office_active_seconds
        awards, self.office_seconds = divmod(self.office_seconds + seconds, OFFICE_POINT_SECONDS)
        self.office_points += int(awards)
        events = self._advance_companion(self.office_points) if awards else []
        events.extend(self._finish_expeditions())
        if gift_found:
            events.append(t("gift.found"))
        active_time = self._office_active_seconds
        if awards or events or any(
            pot.planted_at is not None
            and previous_time - pot.planted_at < BERRY_GROW_SECONDS <= active_time - pot.planted_at
            for pot in self.berry_pots
        ):
            self.save()
        return events

    def currency(self, total_points: int) -> int:
        return max(0, total_points + self.office_shop_bonus - self.currency_anchor - self.spent)

    def _roll_gift(self) -> dict:
        item = self.rng.choices(tuple(GIFT_ITEM_WEIGHTS), weights=tuple(GIFT_ITEM_WEIGHTS.values()))[0]
        amount = self.rng.randint(1, 3) if item == "points" else 1
        return {"item": item, "amount": amount}

    def _grant_gift(self, gift: dict) -> str:
        item, amount = gift["item"], gift["amount"]
        if item == "points":
            self.office_shop_bonus += amount
            return t("gift.received", item=t("gift.points"), amount=amount)
        attribute = BAG_ITEM_FIELDS[item]
        setattr(self, attribute, getattr(self, attribute) + amount)
        return t("gift.received", item=t(f"item.{item}"), amount=amount)

    def offer_visitor_gift(self, identity: tuple[int, bool]) -> bool:
        with self.lock:
            if not self.initialized or self.pending_gift is not None or self.visitor_gift is not None:
                return False
            if self.rng.random() >= VISITOR_GIFT_CHANCE:
                return False
            self.visitor_gift = (identity, self._roll_gift())
            return True

    def dismiss_visitor_gift(self, identity: tuple[int, bool]) -> None:
        with self.lock:
            if self.visitor_gift is not None and self.visitor_gift[0] == identity:
                self.visitor_gift = None

    @_transaction
    def claim_visitor_gift(self, identity: tuple[int, bool]) -> str | None:
        if self.visitor_gift is None or self.visitor_gift[0] != identity:
            return None
        message = self._grant_gift(self.visitor_gift[1])
        self.visitor_gift = None
        self.save()
        return message

    @_transaction
    def reward_fog_visitor(self) -> str | None:
        if not self.initialized or not self.incense_status()[0]:
            return None
        self.office_shop_bonus += FOG_VISITOR_POINTS
        self.save()
        return t("incense.disguise_found", points=FOG_VISITOR_POINTS)

    @_transaction
    def claim_gift(self) -> str | None:
        """Persist a manual claim once, rolling back if the write fails."""
        if self.pending_gift is None:
            return None
        message = self._grant_gift(self.pending_gift)
        self.pending_gift = None
        self.gift_wait_seconds = self._next_gift_wait()
        self.gift_elapsed_seconds = 0.0
        self.save()
        return message

    # ---- the loop --------------------------------------------------

    def _advance_companion(self, total_points: int) -> list[str]:
        """Process any milestones reached by this point award."""
        events: list[str] = []
        for _ in range(64):
            if self.collection_complete:
                break
            c = self.companion
            progress = self.progress(total_points)
            if progress < self.goal():
                break
            if not c.hatched:
                reached_at = c.anchor + max(0, self.goal() - c.bonus)
                events.append(self._hatch(reached_at))
            elif c.stage < len(c.path) - 1:
                events.append(self._evolve())
            else:
                reached_at = c.anchor + max(0, self.goal() - c.bonus)
                events.append(self._graduate(reached_at))

        return events

    def _roll_species(self, floor: list[str] | None) -> int:
        pool = self._eligible_bases(self.companion.shiny, floor)
        weights = [self.dex.species[sid].capture_rate for sid in pool]
        return self.rng.choices(pool, weights=weights, k=1)[0]

    def _hatch(self, total_points: int) -> str:
        c = self.companion
        self._roll_egg_shiny(c)
        # A legacy graded egg may refer to a pool now fully graduated. Keep
        # the egg usable and fall back to the remaining overall collection.
        if not (self._eligible_bases(False, c.egg_floor)
                or self._eligible_bases(True, c.egg_floor)):
            c.egg_floor = None
        if not self._eligible_bases(c.shiny, c.egg_floor):
            c.shiny = not c.shiny
        base = self._roll_species(c.egg_floor)
        species = self.dex.species[base]

        c.nature = self.rng.choice(NATURES)
        paths = self._available_paths(base, c.shiny)
        # Preserve the original equal-per-branch odds among remaining choices.
        c.path = [base]
        while len(c.path) < max(map(len, paths)):
            choices = sorted({path[len(c.path)] for path in paths
                              if len(path) > len(c.path) and path[:len(c.path)] == c.path})
            if not choices:
                break
            c.path.append(self.rng.choice(choices))
        c.stage = 0
        c.hatched = True
        c.rarity = species.rarity
        c.anchor = total_points
        c.bonus = 0
        c.egg_floor = None
        c.born_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

        self._record(base)
        return t("ev.hatched", name=species.name(lang()), rarity=tr_rarity(c.rarity),
                 nature=tr_nature(c.nature),
                 shiny=t("ev.shiny_suffix") if c.shiny else "")

    def _evolve(self) -> str:
        c = self.companion
        before = self.dex.species[c.path[c.stage]].name(lang())
        c.stage += 1
        after_species = self.dex.species[c.path[c.stage]]
        self._record(after_species.id)
        return t("ev.evolved", before=before, after=after_species.name(lang()))

    def _graduate(self, total_points: int) -> str:
        c = self.companion
        final = self.dex.species[c.path[-1]]
        self.catch_log.insert(0, {
            "line": c.path,
            "final": final.id,
            "shiny": c.shiny,
            "nature": c.nature,
            "rarity": c.rarity,
            "caught_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        self.catch_log = self.catch_log[:300]
        self.graduated[c.shiny].add(final.id)
        name = final.name(lang())
        if self.collection_complete:
            return t("ev.collection_complete")
        self.companion = self._new_egg(total_points)
        return t("ev.graduated", name=name)

    def _record(self, species_id: int) -> None:
        entry = self.pokedex.setdefault(species_id, {"shiny": False, "count": 0})
        entry["count"] += 1
        if self.companion.shiny:
            entry["shiny"] = True

    # ---- bag & shop ------------------------------------------------

    def bag_count(self, item: str) -> int:
        return getattr(self, BAG_ITEM_FIELDS[item])

    def sale_price(self, item: str) -> int:
        return self.shop_prices[item] // 2

    def _change_soothe_bells(self, quantity: int) -> None:
        self.soothe_bell += quantity
        if self.pending_gift is None:
            remaining = max(0, self.gift_wait_seconds - self.gift_elapsed_seconds)
            self.gift_wait_seconds = self.gift_elapsed_seconds + remaining / (2 ** quantity)

    @_transaction
    def sell(self, item: str, quantity: int) -> str:
        if item not in BAG_ITEM_FIELDS:
            return t("ev.unknown_item")
        owned = self.bag_count(item)
        if type(quantity) is not int or not 1 <= quantity <= owned:
            return t("bag.sale.invalid_quantity")
        points = self.sale_price(item) * quantity
        if item == "soothe_bell":
            self._change_soothe_bells(-quantity)
        else:
            setattr(self, BAG_ITEM_FIELDS[item], owned - quantity)
        self.office_shop_bonus += points
        self.save()
        return t("bag.sale.sold", item=t(f"item.{item}"), quantity=format(quantity, ","),
                 points=format(points, ","))

    @_transaction
    def use_candy(self) -> str | None:
        if self.candies <= 0:
            return None
        if not self.companion.hatched:
            return t("ev.candy_need")
        if self.collection_complete:
            return t("ev.collection_complete")
        self.candies -= 1
        self.companion.bonus += OFFICE_CANDY_POINTS
        events = self._advance_companion(self.office_points)
        self.save()
        message = t("ev.candy_used.office", points=OFFICE_CANDY_POINTS)
        return CandyUseNotice("\n".join([message, *events]))

    @_transaction
    def use_mint(self) -> str | None:
        if self.mints <= 0:
            return None
        if not self.companion.hatched:
            return t("ev.mint_need")
        self.mints -= 1
        old = self.companion.nature
        choices = [n for n in NATURES if n != old]
        self.companion.nature = self.rng.choice(choices)
        self.save()
        return t("ev.mint_used", old=tr_nature(old), new=tr_nature(self.companion.nature))

    def incense_status(self) -> tuple[bool, float]:
        with self.lock:
            running = self.incense_until - time()
            return running > 0, max(running, self.incense_bank)

    @_transaction
    def toggle_incense(self) -> None:
        now = time()
        if self.incense_until > now:
            self.incense_bank = self.incense_until - now
            self.incense_until = 0.0
        elif self.incense_bank > 0:
            self.incense_until = now + self.incense_bank
            self.incense_bank = 0.0
        else:
            return
        self.save()

    @_transaction
    def use_incense(self) -> str | None:
        if self.incense <= 0:
            return None
        self.incense -= 1
        if self.incense_until > time():
            self.incense_until += INCENSE_SECONDS
        else:
            self.incense_bank += INCENSE_SECONDS
        self.save()
        return t("ev.incense_used")

    @_transaction
    def buy(self, item: str, total_points: int, *, expected_companion: Companion | None = None) -> str:
        price = self.shop_prices.get(item)
        if price is None:
            return t("ev.unknown_item")
        if item == "shiny_charm" and self.shiny_charms >= MAX_SHINY_CHARMS:
            return t("ev.charm_limit", maximum=MAX_SHINY_CHARMS)
        if item == "soothe_bell" and self.soothe_bell >= MAX_SOOTHE_BELLS:
            return t("ev.bell_limit", maximum=MAX_SOOTHE_BELLS)
        if item in EGG_FLOORS:
            if expected_companion is not None and self.companion is not expected_companion:
                return t("ev.egg_companion_changed")
            if not self.can_buy_egg(item):
                return t("ev.egg_pool_complete")
        if self.currency(total_points) < price:
            return t("ev.too_poor")
        if item == "soothe_bell":
            self.spent += price
            self._change_soothe_bells(1)
            self.save()
            return t("ev.bell_bought")
        self.spent += price

        if item == "rare_candy":
            self.candies += 1
            msg = t("ev.bought", item=t("item.rare_candy"))
        elif item == "mint":
            self.mints += 1
            msg = t("ev.bought", item=t("item.mint"))
        elif item == "incense":
            self.incense += 1
            msg = t("ev.bought", item=t("item.incense"))
        elif item == "shiny_charm":
            self.shiny_charms += 1
            msg = t("ev.charm_bought", chance=f"{100 / self.shiny_odds():.1f}")
        else:
            floor = EGG_FLOORS.get(item)
            self.companion = self._new_egg(total_points, floor)
            msg = t("ev.egg_bought", item=t(f"item.{item}"))
        self.save()
        return msg

    def shiny_odds(self) -> float:
        count = min(MAX_SHINY_CHARMS, max(0, self.shiny_charms))
        return max(1 / MAX_SHINY_CHANCE, BASE_SHINY_ODDS * (SHINY_CHARM_FACTOR ** count))
