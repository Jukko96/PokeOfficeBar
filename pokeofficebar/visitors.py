"""Transient desktop visits from the current save's graduates."""

from __future__ import annotations

import tkinter as tk
from math import hypot
from random import choice, randint, random, uniform
from time import monotonic

from .app import ROAM_TASKBAR
from .art import FOG_VISITOR_ID
from .desktop import move_window, pet_window, pointer_work_area, prevent_activation
from .ui import SpriteView

DISGUISE_CHANCE = 0.05
DISGUISE_SQUASH_SECONDS = 0.2
TRUE_FORM_SECONDS = 1.1


class Visitor(tk.Toplevel):
    def __init__(self, master, app, identity, work, now, gift, *, disguised=False):
        super().__init__(master)
        self.app = app
        self.identity = identity
        self.disguised = disguised
        self._phase = "normal"
        self._change_at = now + uniform(4, 8) if disguised else None
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-transparentcolor", "#010101")
        self.configure(bg="#010101")
        self.sprite = SpriteView(self, app, size=app.config.pet_size,
                                 matte=True, walking=True, bg="#010101")
        self.sprite.pack()
        self.sprite.set_overlay(gift)
        self.sprite.show(*identity)
        self.sprite.bind("<ButtonPress-1>", self._press)
        self.sprite.bind("<B1-Motion>", self._drag_to)
        self.sprite.bind("<ButtonRelease-1>", self._release)
        self._drag_origin: tuple[int, int, int, int] | None = None
        self._dragged = False
        self._pressed_gift = False
        self.expires = now + uniform(25, 65)
        self.walk_at = now + uniform(0.5, 2)
        self.target = None
        left, top, right, bottom = self._bounds(work, self.sprite.size)
        x, y = randint(left, right), randint(top, bottom)
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.update_idletasks()
        prevent_activation(self)
        self.deiconify()
        self.update_idletasks()
        if (window := pet_window(self)) is not None:
            move_window(window[0], x, y)

    def _hits_gift(self, event) -> bool:
        return self.sprite.hits_overlay(event.x_root - self.sprite.winfo_rootx(),
                                        event.y_root - self.sprite.winfo_rooty())

    def _press(self, event) -> str:
        if (window := pet_window(self)) is not None:
            _, rect, _ = window
            self._drag_origin = (event.x_root, event.y_root, rect.left, rect.top)
            self._dragged = False
            self._pressed_gift = self._hits_gift(event)
            self._rest(monotonic())
        return "break"

    def _drag_to(self, event) -> str:
        if self._drag_origin is None:
            return "break"
        press_x, press_y, x, y = self._drag_origin
        dx, dy = event.x_root - press_x, event.y_root - press_y
        if self._dragged or max(abs(dx), abs(dy)) > 3:
            self._dragged = True
            if (window := pet_window(self)) is not None:
                move_window(window[0], x + dx, y + dy)
        return "break"

    def _release(self, event) -> str:
        if self._drag_origin is None:
            return "break"
        press_x, press_y, _, _ = self._drag_origin
        self._drag_origin = None
        now = monotonic()
        self._rest(now)
        if self._dragged or now >= self.expires:
            return "break"
        if self.disguised and self._phase != "found":
            if (max(abs(event.x_root - press_x), abs(event.y_root - press_y)) <= 3
                    and self.app.discover_fog_visitor()):
                self._phase = "found"
                self._change_at = None
                self.sprite.show(FOG_VISITOR_ID, False)
        elif self._pressed_gift and self._hits_gift(event) and self.app.claim_visitor_gift(self.identity):
            self.sprite.set_overlay(None)
            self.sprite.show(*self.identity)
        return "break"

    def tick(self, now: float) -> None:
        if self._change_at is not None and now >= self._change_at and self._drag_origin is None:
            if self._phase == "normal":
                self._rest(now)
                self._phase = "squashed"
                self._change_at = now + DISGUISE_SQUASH_SECONDS
                self.sprite.show(*self.identity, squashed=True)
            elif self._phase == "squashed":
                self._phase = "revealed"
                self._change_at = now + TRUE_FORM_SECONDS
                self.sprite.show(FOG_VISITOR_ID, False)
            else:
                self._phase = "normal"
                self._change_at = now + uniform(4, 8)
                self.sprite.show(*self.identity)
        if self._phase == "normal":
            self.walk(now)

    def _rest(self, now: float) -> None:
        self.target = None
        self.walk_at = now + uniform(1.5, 5)
        self.sprite.resume_idle()

    def _bounds(self, work, size):
        right = max(work.left, work.right - size)
        bottom = max(work.top, work.bottom - size)
        if self.sprite.app.config.pet_roam_mode == ROAM_TASKBAR:
            y = max(work.top, bottom - 8)
            return work.left, y, right, y
        return work.left, work.top, right, bottom

    def walk(self, now):
        if self._drag_origin is not None or now < self.walk_at or (window := pet_window(self)) is None:
            return
        hwnd, rect, work = window
        left, top, right, bottom = self._bounds(work, self.sprite.size)
        x, y = rect.left, rect.top
        if not (left <= x <= right and top <= y <= bottom):
            move_window(hwnd, max(left, min(x, right)), max(top, min(y, bottom)))
            self.target = None
            self.sprite.resume_idle()
            return
        if self.target is None:
            self.target = (randint(max(left, x - 52), min(right, x + 52)),
                           randint(max(top, y - 30), min(bottom, y + 30)))
        dx, dy = self.target[0] - x, self.target[1] - y
        distance = hypot(dx, dy)
        if distance and self.sprite.advance_walk():
            step = min(1, 4 / distance)
            if move_window(hwnd, x + round(dx * step), y + round(dy * step)):
                return
        self._rest(now)


class DesktopVisits:
    """One Tk timer manages every visitor and releases windows on pause."""

    def __init__(self, root, app, refresh_status):
        self.root = root
        self.app = app
        self.refresh_status = refresh_status
        self.visitors: dict[tuple[int, bool], Visitor] = {}
        self.job = None
        self.arrival = None
        self.refresh_at = 0.0

    def sync(self):
        if not self.app.ready or not self.app.game.incense_status()[0]:
            self.close()
            return
        while len(self.visitors) > self.app.config.incense_max_visitors:
            self._remove(next(reversed(self.visitors)))
        if self.job is None:
            self._tick()

    def close(self):
        if self.job is not None:
            self.root.after_cancel(self.job)
            self.job = None
        for identity in tuple(self.visitors):
            self._remove(identity)
        self.arrival = None

    def _remove(self, identity):
        visitor = self.visitors.pop(identity)
        self.app.game.dismiss_visitor_gift(identity)
        visitor.destroy()

    def _tick(self):
        self.job = None
        if not self.app.game.incense_status()[0]:
            self.close()
            self.refresh_status()
            return

        now = monotonic()
        self.job = self.root.after(125, self._tick)
        if now >= self.refresh_at:
            self.refresh_at = now + 1
            self.refresh_status()
        for identity, visitor in list(self.visitors.items()):
            if now >= visitor.expires:
                self._remove(identity)
            else:
                visitor.tick(now)
        if self.arrival is None:
            self.arrival = now + uniform(1, 3)
        elif now >= self.arrival:
            self.arrival = now + uniform(6, 14)
            self._arrive(now)

    def _arrive(self, now):
        slots = self.app.config.incense_max_visitors - len(self.visitors)
        if slots <= 0:
            return
        work = pointer_work_area()
        if work is None:
            return
        game = self.app.game
        with game.lock:
            species = self.app.dex.species
            graduates = {
                (sid, bool(record.get("shiny")))
                for record in game.catch_log
                if record.get("final") in species
                for sid in (*record.get("line", ()), record["final"])
                if sid in species
            }
        available = list(graduates.difference(self.visitors))
        for _ in range(min(slots, randint(1, 2))):
            if not available:
                break
            identity = choice(available)
            available.remove(identity)
            if game.dex.sprite_path(*identity, fetch=False) is None:
                self.app.frames(*identity, self.app.config.pet_size)
                continue
            disguise_open = not any(visitor.disguised for visitor in self.visitors.values())
            disguised = disguise_open and random() < DISGUISE_CHANCE
            gift = None
            if not disguised and game.offer_visitor_gift(identity):
                gift = self.app.item_image("gift_box", 40)
                if gift is None:
                    game.dismiss_visitor_gift(identity)
            try:
                self.visitors[identity] = Visitor(self.root, self.app, identity, work, now, gift,
                                                  disguised=disguised)
            except Exception:
                game.dismiss_visitor_gift(identity)
                raise
