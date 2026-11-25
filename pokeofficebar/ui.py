"""Tkinter surfaces: the main window, and the floating desktop pet.

Windows has no menu-bar text the way macOS does, so the glanceable readout the
original puts in the menu bar lives in two places here: the tray tooltip, and
an optional always-on-top floating pet.
"""

from __future__ import annotations

import tkinter as tk
import webbrowser
from datetime import datetime
from dataclasses import replace
from functools import wraps
from math import ceil, hypot
from random import randint, uniform
from time import monotonic
from tkinter import ttk

from PIL import Image, ImageFilter, ImageOps, ImageTk

from . import __version__
from .app import ROAM_OFF, ROAM_TASKBAR, WORK_TIMES, asset_dir, normalize_work_time
from .desktop import move_window, pet_window, pointer_over, prevent_activation
from .game import (
    BERRY_POT_COUNT, BERRY_POT_PRICE, CandyUseNotice, EGG_FLOORS, EXPEDITION_DESTINATIONS,
    RARITY_ORDER, MAX_SHINY_CHARMS, MAX_SOOTHE_BELLS,
)
from .i18n import nature as tr_nature, rarity as tr_rarity, set_lang, t
from .updates import RELEASES_PAGE

BG = "#16171d"
PANEL = "#1e2028"
FG = "#e8e8ef"
MUTED = "#9aa0b0"
ACCENT = "#f2b544"
GOOD = "#5ad18b"

RARITY_COLOR = {
    "Common": "#8d93a3",
    "Uncommon": "#5ad18b",
    "Rare": "#6aa8f0",
    "Very Rare": "#b98cf0",
    "Legendary": "#f2b544",
}

DEX_COLS, DEX_ROWS = 4, 6
DEX_PER_PAGE = DEX_COLS * DEX_ROWS      # 24, matching the original
DEX_SPRITE = 52
LOG_SPRITE = 44
ITEM_ICON = 34


def _game_view(method):
    @wraps(method)
    def render(self, *args, **kwargs):
        with self.app.game.lock:
            return method(self, *args, **kwargs)
    return render


def _duration(seconds: float) -> str:
    minutes, seconds = divmod(round(seconds), 60)
    key = "duration.minutes_seconds" if minutes and seconds else (
        "duration.minutes" if minutes else "duration.seconds")
    return t(key, minutes=minutes, seconds=seconds)


def _rest_duration(seconds: float) -> str:
    hours, minutes = divmod(ceil(seconds / 60), 60)
    return (t("expedition.rest_hours", hours=hours, minutes=minutes)
            if hours else t("duration.minutes", minutes=minutes))


def _local_timestamp(timestamp: float) -> str:
    try:
        return datetime.fromtimestamp(ceil(timestamp)).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return ""


def _matte(img, threshold: int = 128):
    """Force alpha to 0 or 255.

    A `-transparentcolor` window keys out exactly one colour. Anti-aliased edge
    pixels get blended with that key colour and land *near* it but not on it, so
    they survive as a dark halo around the sprite. Making the alpha binary means
    every pixel is either exactly the key colour or fully opaque, and the halo
    disappears. Only needed on the floating pet; normal windows composite fine.
    """
    alpha = img.getchannel("A").point(lambda v: 255 if v >= threshold else 0)
    out = img.copy()
    out.putalpha(alpha)
    return out


class SpriteView(tk.Label):
    """A label that plays an animated sprite."""

    def __init__(self, master, app, size: int = 96, matte: bool = False,
                 walking: bool = False, **kw) -> None:
        super().__init__(master, bd=0, highlightthickness=0, bg=kw.pop("bg", PANEL), **kw)
        self.app = app
        self.size = size
        self.matte = matte
        self.walking = walking
        self._frames: list[ImageTk.PhotoImage] = []
        self._walk_frames: list[ImageTk.PhotoImage] = []
        self._walk_index: int | None = None
        self._overlay: Image.Image | None = None
        self._index = 0
        self._job = None
        self._key = None

    def set_overlay(self, image: Image.Image | None) -> None:
        if image is not self._overlay:
            self._overlay = image
            self._key = None

    def overlay_position(self) -> tuple[int, int]:
        if self._overlay is None:
            return 0, 0
        return max(0, self.size - self._overlay.width - 2), 2

    def hits_overlay(self, x: int, y: int) -> bool:
        image = self._overlay
        if image is None:
            return False
        left, top = self.overlay_position()
        x, y = int(x - left), int(y - top)
        return 0 <= x < image.width and 0 <= y < image.height and image.getpixel((x, y))[3] >= 128

    def _compose_overlay(self, frame: Image.Image) -> Image.Image:
        if self._overlay is None:
            return frame
        composed = frame.copy()
        composed.alpha_composite(self._overlay, dest=self.overlay_position())
        return _matte(composed) if self.matte else composed

    def show(self, species_id: int | None, shiny: bool, *, squashed: bool = False) -> None:
        egg_revision = getattr(self.app, "egg_art_revision", 0) if species_id is None else 0
        key = (species_id, shiny, self.size, squashed, egg_revision)
        if key == self._key:
            return
        if species_id is None:
            images = self.app.egg_frames(self.size, shiny=shiny)
        else:
            images = self.app.frames(species_id, shiny, self.size)
        self._key = key if images else None
        if squashed and images:
            images = [self._squash(images[0])]
        if self.matte:
            images = [_matte(f) for f in images]
        poses = self._walking_poses(images[0]) if self.walking and images and not squashed else []
        self._frames = [ImageTk.PhotoImage(self._compose_overlay(frame)) for frame in images]
        self._walk_frames = [ImageTk.PhotoImage(self._compose_overlay(pose)) for pose in poses]
        self._walk_index = None
        self._index = 0
        self.stop()
        if self._frames:
            self.configure(image=self._frames[0], text="")
            if len(self._frames) > 1:
                self._tick()
        else:
            self.configure(image="", text=t("common.loading"), fg=FG)

    @staticmethod
    def _squash(frame: Image.Image) -> Image.Image:
        bounds = frame.getbbox()
        if bounds is None:
            return frame
        sprite = frame.crop(bounds)
        width = min(frame.width, round(sprite.width * 1.08))
        height = max(1, round(sprite.height * 0.75))
        pose = Image.new("RGBA", frame.size)
        pose.paste(sprite.resize((width, height), Image.Resampling.NEAREST),
                   ((frame.width - width) // 2, bounds[3] - height))
        return pose

    @staticmethod
    def _walking_poses(base: Image.Image) -> list[Image.Image]:
        """Create planted and lifted poses from the base sprite."""
        box = base.getbbox()
        if box is None:
            return []
        left, _, right, ground = box
        sprite = base.crop(box)
        sprite.thumbnail((round(base.width * 0.88), round(base.height * 0.88)),
                         Image.Resampling.NEAREST)
        lift = max(2, round(base.height * 0.045))
        poses = []
        for angle, rise in ((-9, 0), (-3, lift), (9, 0), (3, lift)):
            tilted = sprite.rotate(angle, expand=True)
            pose = Image.new("RGBA", base.size)
            x = min(max(0, (left + right - tilted.width) // 2), base.width - tilted.width)
            pose.paste(tilted, (x, max(0, ground - tilted.height - rise)))
            poses.append(pose)
        return poses

    def _tick(self) -> None:
        self._index = (self._index + 1) % len(self._frames)
        self.configure(image=self._frames[self._index])
        self._job = self.after(110, self._tick)

    def advance_walk(self) -> bool:
        if not self._walk_frames:
            return False
        if self._walk_index is None:
            self.stop()
            self._walk_index = 0
        else:
            self._walk_index = (self._walk_index + 1) % len(self._walk_frames)
        self.configure(image=self._walk_frames[self._walk_index])
        return True

    def resume_idle(self) -> None:
        if self._walk_index is None:
            return
        self._walk_index = None
        self.configure(image=self._frames[self._index])
        if len(self._frames) > 1:
            self._job = self.after(110, self._tick)

    def stop(self) -> None:
        if self._job:
            self.after_cancel(self._job)
            self._job = None

    def destroy(self) -> None:
        self.stop()
        super().destroy()


def _action(parent, text: str, command, enabled: bool) -> tk.Button:
    """A small accent button that visibly greys out when it can't be used."""
    return tk.Button(
        parent, text=text, command=command, relief="flat", cursor="hand2",
        font=("Segoe UI", 9, "bold"), width=5,
        bg=ACCENT if enabled else "#33363f",
        fg="#1a1a1a" if enabled else MUTED,
        disabledforeground=MUTED,
        state="normal" if enabled else "disabled",
    )


class BerryPotArt(tk.Canvas):
    """Draw the planter as it changes from bare soil to fruit."""

    def __init__(self, master):
        super().__init__(master, width=100, height=76, bg=master.cget("bg"), highlightthickness=0)
        self.stage = None

    def show(self, stage: int) -> None:
        if stage == self.stage:
            return
        self.stage = stage
        self.delete("all")
        self.create_oval(47, 141, 173, 161, fill="#191b22", outline="")
        body, shade, rim = (
            ("#616474", "#4e5261", "#787b8a") if stage == -1
            else ("#b96754", "#934d45", "#d18167")
        )
        self.create_polygon(58, 109, 162, 109, 149, 148, 71, 148, fill=body, outline=shade, width=2)
        self.create_polygon(117, 111, 160, 111, 148, 146, 109, 146, fill=shade)
        self.create_rectangle(53, 97, 167, 114, fill=rim, outline=shade, width=2)
        self.create_rectangle(61, 98, 159, 104, fill="#5a433d", outline="")

        if stage > 0:
            top = 69 if stage == 1 else 36
            self.create_line(110, 103, 110, top, fill="#39855e", width=3)
            for x, y, direction in ((110, 88, -1), (110, 79, 1)):
                self._leaf(x, y, direction)
        if stage >= 2:
            for x, y, direction in ((110, 69, -1), (110, 58, 1), (110, 49, -1), (110, 39, 1)):
                self._leaf(x, y, direction)
        if stage == 3:
            for x, y in ((86, 52), (130, 60), (91, 72)):
                self.create_oval(x - 8, y - 8, x + 8, y + 8, fill="#e26b62",
                                 outline="#913f47", width=2)
                self.create_rectangle(x - 4, y - 4, x - 1, y - 1, fill="#ffc091", outline="")
        self.scale("all", 0, 0, 0.45, 0.45)

    def _leaf(self, x: int, y: int, direction: int) -> None:
        self.create_polygon(x, y, x + 12 * direction, y - 15,
                            x + 32 * direction, y - 19, x + 27 * direction, y - 6,
                            x + 12 * direction, y + 1, fill="#64b581", outline="#367554", width=2)


class BerryPotCard(tk.Frame):
    def __init__(self, master, number: int, command):
        bg = "#23262f"
        super().__init__(master, bg=bg)
        self.number = number
        self.title = tk.Label(self, bg=bg, fg=FG, font=("Segoe UI", 9, "bold"))
        self.title.pack(pady=(6, 0))
        self.art = BerryPotArt(self)
        self.art.pack()
        self.status = tk.Label(self, bg=bg, fg=MUTED, font=("Segoe UI", 9))
        self.status.pack()
        self.progress = ttk.Progressbar(self, maximum=100, length=104,
                                        style="Poke.Horizontal.TProgressbar")
        self.progress.pack(pady=(4, 0))
        self.button = _action(self, "", command, enabled=False)
        self.button.configure(width=0, padx=8, pady=3)
        self.button.pack(pady=(6, 7))

    def show(self, growth: float | None, unlocked: bool, enabled: bool) -> None:
        if not unlocked:
            stage, status, action = -1, "locked", "unlock"
        elif growth is None:
            stage, status, action = 0, "empty", "plant"
        elif growth == 1:
            stage, status, action = 3, "ripe", "harvest"
        else:
            stage, status, action = (1 if growth < 0.4 else 2), "growing", "wait"
        percent = (growth or 0) * 100
        self.art.show(stage)
        self.title.configure(text=t("berry.slot", number=self.number))
        self.status.configure(text=t("berry." + status, percent=int(percent)))
        self.progress["value"] = percent
        enabled = enabled and action != "wait"
        self.button.configure(text=t("berry." + action, price=BERRY_POT_PRICE),
                              state="normal" if enabled else "disabled",
                              bg=ACCENT if enabled else "#33363f",
                              fg="#1a1a1a" if enabled else MUTED)


class ExpeditionCard(tk.Frame):
    def __init__(self, master, key, destination, send, claim):
        bg = "#23262f"
        super().__init__(master, bg=bg)
        self.options: list[tuple[int, bool]] = []
        self.reward_pending = False
        self.scene = None
        self._landscape = None
        self._traveler = None
        try:
            with Image.open(asset_dir() / "expeditions" / f"{key}.png") as image:
                self._landscape = ImageOps.fit(image.convert("RGBA"), (84, 84), Image.Resampling.BOX)
                self.scene = ImageTk.PhotoImage(self._landscape, master=self)
        except OSError:
            pass
        if self.scene is not None:
            self._scene_label = tk.Label(self, image=self.scene, bg=bg, borderwidth=0)
            self._scene_label.pack(side="left", padx=(8, 10), pady=8)
        content = tk.Frame(self, bg=bg)
        content.pack(side="left", fill="both", expand=True, padx=(0, 10), pady=(7, 5))
        self.title = tk.Label(content, bg=bg, fg=FG, font=("Segoe UI", 10, "bold"))
        self.title.pack(anchor="w")
        self.details = tk.Label(content, bg=bg, fg=RARITY_COLOR[destination.rarity],
                                font=("Segoe UI", 8), wraplength=270, justify="left")
        self.details.pack(anchor="w")
        controls = tk.Frame(content, bg=bg)
        controls.pack(fill="x", pady=(5, 0))
        self.choice = ttk.Combobox(controls, style="Poke.TCombobox", state="disabled", width=16, height=9)
        self.choice.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.choice.bind("<<ComboboxSelected>>", lambda _event: self._refresh_send())
        def act():
            if self.reward_pending:
                claim()
            else:
                send(self.selected())

        self.send = _action(controls, "", act, enabled=False)
        self.send.configure(width=0, padx=8)
        self.send.pack(side="right")
        self.status = tk.Label(content, bg=bg, fg=GOOD, font=("Segoe UI", 8),
                               wraplength=270, justify="left")
        self.status.pack(anchor="w", pady=(2, 0))

    def show_traveler(self, app, identity: tuple[int, bool] | None) -> None:
        if self._landscape is None or identity == self._traveler:
            return
        scene = self._landscape
        if identity is not None:
            sprite = app.still(*identity, 48)
            if sprite is None:
                return
            figure = Image.new("RGBA", (52, 52))
            figure.alpha_composite(sprite, dest=(2, 2))
            outline = Image.new("RGBA", figure.size, (24, 26, 36, 0))
            outline.putalpha(figure.getchannel("A").filter(ImageFilter.MaxFilter(3)))
            outline.alpha_composite(figure)
            scene = self._landscape.copy()
            scene.alpha_composite(outline, dest=((scene.width - figure.width) // 2,
                                                 scene.height - figure.height - 5))
        self.scene = ImageTk.PhotoImage(scene, master=self)
        self._scene_label.configure(image=self.scene)
        self._traveler = identity

    def selected(self) -> tuple[int, bool] | None:
        index = self.choice.current()
        return self.options[index] if 0 <= index < len(self.options) else None

    def set_options(self, options: list[tuple[tuple[int, bool], str]], busy: bool, pending: bool) -> None:
        previous = self.selected()
        self.reward_pending = pending
        self.options = [identity for identity, _ in options]
        self.choice.configure(values=[label for _, label in options],
                              state="readonly" if options else "disabled")
        if previous in self.options:
            self.choice.current(self.options.index(previous))
        else:
            key = "reward_pending" if pending else "active_choice" if busy else "choose" if options else "none"
            self.choice.set(t("expedition." + key))
        self._refresh_send()

    def _refresh_send(self) -> None:
        enabled = self.reward_pending or self.selected() is not None
        self.send.configure(text=t("expedition.claim" if self.reward_pending else "expedition.send"),
                            state="normal" if enabled else "disabled",
                            bg=ACCENT if enabled else "#33363f",
                            fg="#1a1a1a" if enabled else MUTED)


class ExpeditionRestRow(tk.Frame):
    def __init__(self, master, app, sid: int, variants: tuple[bool, ...], until: float):
        bg = "#23262f"
        super().__init__(master, bg=bg)
        portraits = tk.Frame(self, bg=bg)
        portraits.pack(side="left", padx=(8, 10), pady=8)
        self.portraits = []
        for shiny in variants:
            sprite = app.still(sid, shiny, 40)
            if sprite is not None:
                photo = ImageTk.PhotoImage(sprite, master=self)
                self.portraits.append(photo)
                tk.Label(portraits, image=photo, bg=bg, borderwidth=0).pack(side="left")

        body = tk.Frame(self, bg=bg)
        body.pack(side="left", fill="x", expand=True, padx=(0, 8), pady=6)
        name = app.dex.species[sid].name(app.config.language)
        if len(variants) == 2:
            name = t("expedition.rest_both", name=name)
        elif variants == (True,):
            name = t("expedition.shiny_name", name=name)
        self.name = tk.Label(body, text=name, anchor="w", bg=bg, fg=FG, font=("Segoe UI", 10, "bold"))
        self.name.pack(fill="x")
        self.left = tk.Label(body, anchor="w", bg=bg, fg=ACCENT, font=("Segoe UI", 9))
        self.left.pack(fill="x")
        when = _local_timestamp(until)
        ready_at = t("expedition.ready_at", when=when) if when else ""
        self.ready_at = tk.Label(body, text=ready_at, anchor="w", bg=bg, fg=MUTED, font=("Segoe UI", 8))
        self.ready_at.pack(fill="x")

    def update_time(self, remaining: float) -> None:
        self.left.configure(text=t("expedition.rest", left=_rest_duration(remaining)))


class EggPurchaseDialog(tk.Toplevel):
    def __init__(self, master, item_and_price: str, on_confirm):
        super().__init__(master)
        self.transient(master)
        self.title(t("shop.egg_confirm.title"))
        self.configure(bg=PANEL)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _event: self.destroy())
        tk.Label(self, text=item_and_price, bg=PANEL, fg=FG, font=("Segoe UI", 12, "bold"),
                 justify="left", wraplength=370).pack(anchor="w", padx=18, pady=(16, 8))
        self.warning = tk.Label(self, text=t("shop.egg_confirm.warning"), bg=PANEL, fg=FG,
                                font=("Segoe UI", 9), justify="left", wraplength=370)
        self.warning.pack(anchor="w", padx=18)
        actions = tk.Frame(self, bg=PANEL)
        actions.pack(fill="x", padx=18, pady=16)

        def buy():
            self.destroy()
            on_confirm()

        self.confirm = _action(actions, t("shop.buy"), buy, enabled=True)
        self.confirm.pack(side="right")
        self.cancel = tk.Button(actions, text=t("shop.egg_confirm.cancel"), command=self.destroy,
                                relief="flat", bg="#33363f", fg=FG, width=6, cursor="hand2")
        self.cancel.pack(side="right", padx=(0, 8))
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_reqwidth()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_reqheight()) // 2
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.grab_set()
        self.cancel.focus_set()


class MainWindow(tk.Toplevel):
    def __init__(self, master, app) -> None:
        super().__init__(master)
        self.app = app
        self._images: list = []          # keeps PhotoImages alive
        self._dex_view = "dex"
        self._dex_page = 0
        self._incense_status = None
        self._egg_dialog = None
        self.title(t("app.title"))
        self.configure(bg=BG)
        self.geometry("520x700")
        self.minsize(470, 600)
        self.protocol("WM_DELETE_WINDOW", self.hide)

        self._style()
        self.nb = ttk.Notebook(self, style="Poke.TNotebook")
        self.nb.pack(fill="both", expand=True, padx=10, pady=10)

        self.home = tk.Frame(self.nb, bg=PANEL)
        self.dex_tab = tk.Frame(self.nb, bg=PANEL)
        self.bag_tab = tk.Frame(self.nb, bg=PANEL)
        self.shop_tab = tk.Frame(self.nb, bg=PANEL)
        self.settings_tab = tk.Frame(self.nb, bg=PANEL)
        self._tabs = [
            (self.home, "tab.home"), (self.dex_tab, "tab.pokedex"),
            (self.bag_tab, "tab.bag"), (self.shop_tab, "tab.shop"),
        ]
        self.berry_tab = tk.Frame(self.nb, bg=PANEL)
        self.expedition_tab = tk.Frame(self.nb, bg=PANEL)
        self._tabs.append((self.berry_tab, "tab.berry"))
        self._tabs.append((self.expedition_tab, "tab.expedition"))
        self._tabs.append((self.settings_tab, "tab.settings"))
        for frame, key in self._tabs:
            self.nb.add(frame, text=t(key))

        self._build_home()
        self._build_berry_pot()
        self._build_expeditions()
        self._build_settings()
        self.withdraw()
    def _style(self) -> None:
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("Poke.TNotebook", background=BG, borderwidth=0)
        st.configure("Poke.TNotebook.Tab", background=BG, foreground=MUTED,
                     padding=(12, 6), borderwidth=0)
        st.map("Poke.TNotebook.Tab", background=[("selected", PANEL)],
               foreground=[("selected", FG)])
        st.configure("Poke.Horizontal.TProgressbar", troughcolor="#2a2d38",
                     background=ACCENT, borderwidth=0, thickness=8)
        st.configure("Poke.TCombobox", foreground=FG, fieldbackground="#2a2d38",
                     background="#33363f", arrowcolor=FG)
        st.map("Poke.TCombobox", fieldbackground=[("readonly", "#2a2d38"), ("disabled", "#2a2d38")],
               foreground=[("readonly", FG), ("disabled", MUTED)])

    # ---- home ------------------------------------------------------

    def _build_home(self) -> None:
        pad = {"padx": 16}
        top = tk.Frame(self.home, bg=PANEL)
        top.pack(fill="x", pady=(16, 8), **pad)

        self.sprite = SpriteView(top, self.app, size=96)
        self.sprite.pack(side="left")

        info = tk.Frame(top, bg=PANEL)
        info.pack(side="left", fill="x", expand=True, padx=(14, 0))
        self.name_lbl = tk.Label(info, text=t("common.loading"), bg=PANEL, fg=FG,
                                 font=("Segoe UI", 15, "bold"), anchor="w")
        self.name_lbl.pack(fill="x")
        self.sub_lbl = tk.Label(info, text="", bg=PANEL, fg=MUTED,
                                font=("Segoe UI", 9), anchor="w", justify="left")
        self.sub_lbl.pack(fill="x", pady=(2, 6))
        self.grow_bar = ttk.Progressbar(info, maximum=100,
                                        style="Poke.Horizontal.TProgressbar")
        self.grow_bar.pack(fill="x")
        self.grow_lbl = tk.Label(info, text="", bg=PANEL, fg=MUTED,
                                 font=("Segoe UI", 8), anchor="w")
        self.grow_lbl.pack(fill="x", pady=(3, 0))

        self.line_lbl = tk.Label(self.home, text="", bg=PANEL, fg=MUTED,
                                 font=("Segoe UI", 9), anchor="w")
        self.line_lbl.pack(fill="x", pady=(0, 10), **pad)

        tk.Frame(self.home, bg="#2a2d38", height=1).pack(fill="x", **pad)

        stats = tk.Frame(self.home, bg=PANEL)
        stats.pack(fill="x", pady=(8, 12), **pad)
        self.today_lbl = tk.Label(stats, text="-", bg=PANEL, fg=FG,
                                  font=("Segoe UI", 26, "bold"), anchor="w")
        self.today_lbl.pack(fill="x")
        self.today_sub = tk.Label(stats, text="", bg=PANEL, fg=MUTED,
                                  font=("Segoe UI", 9), anchor="w")
        self.today_sub.pack(fill="x")

        self.totals_lbl = tk.Label(self.home, bg=PANEL, fg=MUTED,
                                   font=("Segoe UI", 9), anchor="w")
        self.totals_lbl.pack(fill="x", padx=16, pady=8)
        gift = self.app.item_image("gift_box", 32)
        self._gift_image = ImageTk.PhotoImage(gift) if gift is not None else None
        self.gift_button = tk.Button(
            self.home, text=t("gift.claim"), command=self.app.claim_gift,
            image=self._gift_image, compound="left", padx=12, pady=5,
            bg=ACCENT, fg=BG, relief="flat", cursor="hand2", font=("Segoe UI", 11, "bold"),
        )
        self.event_lbl = tk.Label(self.home, bg=PANEL, fg=GOOD, wraplength=420,
                                  justify="left", font=("Segoe UI", 9), anchor="w")
        self.event_lbl.pack(fill="x", padx=16, pady=10)
        self._update_row = tk.Frame(self.home, bg=PANEL)
        self._update_message = tk.Label(self._update_row, bg=PANEL, fg=ACCENT, anchor="w")
        self._update_message.pack(side="left", fill="x", expand=True)
        self._update_link = _action(self._update_row, "", lambda: webbrowser.open(RELEASES_PAGE), True)
        self._update_link.configure(width=0, padx=8)
        self._update_link.pack(side="right")

    # ---- settings --------------------------------------------------

    def _build_settings(self) -> None:
        cfg = self.app.config
        wrap = self._scrollable(self.settings_tab)

        self.vars = {
            "language": tk.StringVar(value=cfg.language),
            "floating_pet": tk.BooleanVar(value=cfg.floating_pet),
            "start_with_windows": tk.BooleanVar(value=cfg.start_with_windows),
            "work_timer_enabled": tk.BooleanVar(value=cfg.work_timer_enabled),
            "pet_size": tk.StringVar(value=str(cfg.pet_size)),
            "incense_max_visitors": tk.StringVar(value=str(cfg.incense_max_visitors)),
        }
        self.vars.update({key: tk.StringVar(value=getattr(cfg, key)) for key in WORK_TIMES})

        def field(label: str, key: str, hint: str = "") -> None:
            tk.Label(wrap, text=label, bg=PANEL, fg=FG, anchor="w",
                     font=("Segoe UI", 9, "bold")).pack(fill="x", pady=(10, 2))
            tk.Entry(wrap, textvariable=self.vars[key], bg="#2a2d38", fg=FG,
                     insertbackground=FG, relief="flat").pack(fill="x", ipady=4)
            if hint:
                tk.Label(wrap, text=hint, bg=PANEL, fg=MUTED, anchor="w",
                         font=("Segoe UI", 8), wraplength=400,
                         justify="left").pack(fill="x", pady=(2, 0))

        field(t("set.petsize"), "pet_size", t("set.petsize.hint"))
        field(t("set.incense_max_visitors"), "incense_max_visitors")

        for variable, label in (("floating_pet", "set.pet"), ("start_with_windows", "set.startup")):
            tk.Checkbutton(
                wrap, text=t(label), variable=self.vars[variable], bg=PANEL, fg=FG,
                selectcolor=PANEL, activebackground=PANEL, activeforeground=FG,
                anchor="w", font=("Segoe UI", 9), highlightthickness=0, bd=0,
            ).pack(fill="x", pady=(8, 0))

        timer = tk.Checkbutton(
            wrap, variable=self.vars["work_timer_enabled"], bg=PANEL, fg=FG,
            selectcolor=PANEL, activebackground=PANEL, activeforeground=FG,
            anchor="w", font=("Segoe UI", 9), highlightthickness=0, bd=0,
        )
        timer.pack(fill="x", pady=(12, 2))
        self._work_timer_labels = {"set.work_timer": timer}
        times = tk.Frame(wrap, bg=PANEL)
        times.pack(fill="x", pady=(0, 5))
        for col, key in enumerate(WORK_TIMES):
            times.columnconfigure(col, weight=1, uniform="work_time")
            label = tk.Label(times, bg=PANEL, fg=MUTED, font=("Segoe UI", 8))
            label.grid(row=0, column=col, sticky="w", padx=(0, 8))
            self._work_timer_labels[f"set.{key}"] = label
            tk.Entry(times, width=8, textvariable=self.vars[key], bg="#2a2d38",
                     fg=FG, insertbackground=FG, relief="flat").grid(
                         row=1, column=col, sticky="ew", padx=(0, 8), ipady=4)
        self._label_work_timer()

        tk.Label(wrap, text=t("set.language"), bg=PANEL, fg=FG, anchor="w",
                 font=("Segoe UI", 9, "bold")).pack(fill="x", pady=(12, 2))
        langs = tk.Frame(wrap, bg=PANEL)
        langs.pack(fill="x")
        for value, text in (("ko", "한국어"), ("en", "English")):
            tk.Radiobutton(
                langs, text=text, value=value, variable=self.vars["language"],
                bg=PANEL, fg=FG, selectcolor=PANEL, activebackground=PANEL,
                activeforeground=FG, font=("Segoe UI", 9), highlightthickness=0, bd=0,
            ).pack(side="left", padx=(0, 12))

        # Showing the path makes it obvious which save is in play — sandboxed
        # launchers can silently redirect %LOCALAPPDATA% elsewhere.
        tk.Label(wrap, text=t("set.datadir"), bg=PANEL, fg=FG, anchor="w",
                 font=("Segoe UI", 9, "bold")).pack(fill="x", pady=(14, 2))
        path_box = tk.Entry(wrap, bg="#23262f", fg=MUTED, insertbackground=FG,
                            relief="flat", font=("Consolas", 8))
        path_box.insert(0, str(self.app.game.path.parent))
        path_box.configure(state="readonly", readonlybackground="#23262f")
        path_box.pack(fill="x", ipady=3)

        tk.Button(wrap, text=t("set.save"), command=self._save_settings, bg=ACCENT,
                  fg="#1a1a1a", relief="flat", font=("Segoe UI", 10, "bold"),
                  cursor="hand2").pack(fill="x", pady=(18, 0), ipady=6)
        self.settings_msg = tk.Label(wrap, text="", bg=PANEL, fg=GOOD,
                                     font=("Segoe UI", 9), wraplength=400)
        self.settings_msg.pack(fill="x", pady=(8, 0))
        if self.app.startup_error:
            self.settings_msg.configure(text=t("set.startup_failed"), fg="#e0665f")
        self._version_details = tk.Label(wrap, bg=PANEL, fg=MUTED, anchor="w")
        self._version_details.pack(fill="x", pady=(10, 0))
        self._refresh_version()

    def _save_settings(self) -> None:
        cfg = replace(self.app.config)
        try:
            cfg.pet_size = max(48, min(192, int(self.vars["pet_size"].get())))
            cfg.incense_max_visitors = max(1, int(self.vars["incense_max_visitors"].get()))
        except ValueError:
            self.settings_msg.configure(text=t("set.numbers"), fg="#e0665f")
            return
        cfg.floating_pet = self.vars["floating_pet"].get()
        cfg.start_with_windows = self.vars["start_with_windows"].get()
        cfg.work_timer_enabled = self.vars["work_timer_enabled"].get()
        for key in WORK_TIMES:
            value = normalize_work_time(self.vars[key].get())
            if value is None:
                self.settings_msg.configure(
                    text=t("set.work_time_invalid", field=t(f"set.{key}")), fg="#e0665f")
                return
            setattr(cfg, key, value)
        if not cfg.valid_work_schedule():
            self.settings_msg.configure(text=t("set.work_time_order"), fg="#e0665f")
            return
        cfg.language = self.vars["language"].get()
        set_lang(cfg.language)
        try:
            cfg.save(self.app.config_path)
        except OSError:
            self.settings_msg.configure(text=t("save.retry"), fg="#e0665f")
            return
        self.app.config = cfg
        self.app.sync_windows_startup()
        self.vars["incense_max_visitors"].set(str(cfg.incense_max_visitors))
        for key in WORK_TIMES:
            self.vars[key].set(getattr(cfg, key))
        self._retitle()
        self.settings_msg.configure(text=t("set.saved"), fg=GOOD)
        if self.app.startup_error:
            self.settings_msg.configure(text=t("set.startup_failed"), fg="#e0665f")
        self.event_generate("<<SettingsChanged>>")

    def _label_work_timer(self) -> None:
        for key, widget in self._work_timer_labels.items():
            widget.configure(text=t(key))

    def _retitle(self) -> None:
        """Re-label window chrome after a language change."""
        self.title(t("app.title"))
        for i, (_frame, key) in enumerate(self._tabs):
            self.nb.tab(i, text=t(key))
        self._label_work_timer()

    # ---- rendering -------------------------------------------------

    def show(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def hide(self) -> None:
        self.withdraw()

    @_game_view
    def render(self, events: list[str]) -> None:
        app, game = self.app, self.app.game
        lang = app.config.language
        self._refresh_version()

        if app.error:
            self.name_lbl.configure(text=t("common.problem"))
            self.sub_lbl.configure(text=app.error)
            return
        if not app.ready:
            return

        c = game.companion
        if c.hatched and c.species_id is not None:
            species = app.dex.species[c.species_id]
            self.sprite.show(c.species_id, c.shiny)
            star = " ✨" if c.shiny else ""
            self.name_lbl.configure(text=f"{species.name(lang)}{star}")
            self.sub_lbl.configure(text=t("home.subtitle", rarity=tr_rarity(c.rarity),
                                          nature=tr_nature(c.nature)))
            names = " → ".join(app.dex.species[s].name(lang) for s in c.path)
            self.line_lbl.configure(text=t("home.line", names=names))
        else:
            self.sprite.show(None, c.shiny)
            self.name_lbl.configure(text=t("egg.shiny" if c.shiny else "egg.name"))
            self.sub_lbl.configure(text=t("office.egg"))
            self.line_lbl.configure(text="")

        progress, goal = game.progress(app.game_total), game.goal()
        pct = min(progress / max(1, goal), 1.0)
        self.grow_bar["value"] = pct * 100
        step = t("step.hatch") if not c.hatched else (
            t("step.evolve") if c.stage < len(c.path) - 1 else t("step.graduate")
        )
        self.grow_lbl.configure(text=t(
            "office.progress",
            done=format(progress, ","), goal=format(goal, ","), step=step))
        if game.collection_complete:
            self.grow_bar["value"] = 100
            self.grow_lbl.configure(text=t("ev.collection_complete"))

        self._render_office(events)

    def _refresh_version(self) -> None:
        app = self.app
        status = app.update_status
        result = t(f"updates.{status}", version=app.available_version)
        if status in {"available", "installing", "install_failed"}:
            self._update_message.configure(text=result)
            if status == "installing":
                self._update_link.pack_forget()
            else:
                self._update_link.configure(text=t("updates.download"))
                if not self._update_link.winfo_manager():
                    self._update_link.pack(side="right")
            if not self._update_row.winfo_manager():
                self._update_row.pack(fill="x", padx=16, pady=(4, 0), before=self.event_lbl)
        else:
            self._update_row.pack_forget()
        self._version_details.configure(text=f"v{__version__} · {result}")

    def _render_office(self, events) -> None:
        game = self.app.game
        self.today_lbl.configure(text=t("office.balance", balance=game.currency(game.office_points)))
        self._refresh_expeditions()
        self.refresh_office_clock()
        self.totals_lbl.configure(text=t("office.total", points=game.office_points, count=len(game.catch_log)))
        if game.pending_gift is not None:
            self.gift_button.pack(fill="x", padx=16, pady=10, before=self.event_lbl)
        else:
            self.gift_button.pack_forget()
        if events:
            self.event_lbl.configure(text="\n".join(events[-3:]))
        self._images.clear()
        self._render_pokedex()
        self._render_bag()
        for event in events:
            if isinstance(event, CandyUseNotice):
                self.bag_msg.configure(text=event)
        self._render_shop()

    def refresh_office_clock(self) -> None:
        key = "office.paused" if self.app.office_paused else "office.status"
        self.today_sub.configure(text=t(key))
        self._refresh_berry_pot()
        self._refresh_expedition_status()

    def _build_berry_pot(self) -> None:
        wrap = tk.Frame(self.berry_tab, bg=PANEL)
        wrap.pack(fill="both", expand=True, padx=20, pady=10)
        self._berry_title = tk.Label(wrap, bg=PANEL, fg=FG, font=("Segoe UI", 15, "bold"))
        self._berry_title.pack()
        self._berry_hint = tk.Label(wrap, bg=PANEL, fg=MUTED, font=("Segoe UI", 9),
                                    wraplength=340, justify="center")
        self._berry_hint.pack(pady=(4, 5))
        actions = tk.Frame(wrap, bg=PANEL)
        actions.pack(fill="x", padx=4, pady=(0, 4))
        self._berry_balance = tk.Label(actions, bg=PANEL, fg=FG, font=("Segoe UI", 9, "bold"))
        self._berry_balance.pack(side="left")
        self._berry_batch_action = None
        self._berry_batch_button = _action(actions, "", self._tend_berry_batch, enabled=False)
        self._berry_batch_button.configure(width=0, padx=8, pady=2)
        self._berry_batch_button.pack(side="right")
        grid = tk.Frame(wrap, bg=PANEL)
        grid.pack(fill="x")
        grid.columnconfigure((0, 1), weight=1, uniform="berry")
        self._berry_cards = []
        for slot in range(BERRY_POT_COUNT):
            card = BerryPotCard(grid, slot + 1, lambda slot=slot: self._tend_berry_pot(slot))
            row, column = divmod(slot, 2)
            card.grid(row=row, column=column, padx=4, pady=3, sticky="ew")
            self._berry_cards.append(card)
        self._berry_message = tk.Label(wrap, bg=PANEL, fg=GOOD, font=("Segoe UI", 9))
        self._berry_message.pack(pady=(6, 0))
        self._refresh_berry_pot()

    def _refresh_berry_pot(self) -> None:
        game = self.app.game
        balance = game.currency(game.office_points)
        self._berry_title.configure(text=t("berry.title"))
        self._berry_hint.configure(text=t("berry.hint"))
        self._berry_balance.configure(text=t("office.balance", balance=balance))
        ripe = False
        empty = False
        for slot, card in enumerate(self._berry_cards):
            unlocked = game.berry_pots[slot].unlocked
            enabled = self.app.ready and (unlocked or balance >= BERRY_POT_PRICE)
            growth = game.berry_growth(slot)
            ripe = ripe or (unlocked and growth == 1.0)
            empty = empty or (unlocked and growth is None)
            card.show(growth, unlocked, enabled)
        action = None
        label = "berry.harvest_all"
        if self.app.ready:
            if ripe:
                action = game.harvest_ripe_berries
            elif empty:
                action = game.plant_all_berries
                label = "berry.plant_all"
        self._berry_batch_action = action
        self._berry_batch_button.configure(
            text=t(label), state="normal" if action else "disabled",
            bg=ACCENT if action else "#33363f", fg="#1a1a1a" if action else MUTED,
        )

    def _tend_berry_batch(self) -> None:
        if self._berry_batch_action is not None:
            self._apply_berry_action(self._berry_batch_action)

    def _tend_berry_pot(self, slot: int) -> None:
        game = self.app.game
        if not game.berry_pots[slot].unlocked:
            action = game.unlock_berry_pot
        elif game.berry_growth(slot) is None:
            action = game.plant_berry
        else:
            action = game.harvest_berry
        self._apply_berry_action(action, slot)

    def _apply_berry_action(self, action, *args) -> None:
        try:
            message = action(*args)
        except OSError:
            self._berry_message.configure(text=t("save.retry"), fg="#e0665f")
            return
        if message:
            self.render([])
            self._berry_message.configure(text=message, fg=GOOD)

    def _build_expeditions(self) -> None:
        wrap = tk.Frame(self.expedition_tab, bg=PANEL)
        wrap.pack(fill="both", expand=True, padx=14, pady=10)
        self._expedition_title = tk.Label(wrap, bg=PANEL, fg=FG, font=("Segoe UI", 14, "bold"))
        self._expedition_title.pack(anchor="w")
        self._expedition_hint = tk.Label(wrap, bg=PANEL, fg=MUTED, font=("Segoe UI", 9),
                                         wraplength=365, justify="left")
        self._expedition_hint.pack(anchor="w", pady=(3, 7))
        self._expedition_message = tk.Label(wrap, bg=PANEL, fg="#e0665f", font=("Segoe UI", 9))
        self._expedition_message.pack(side="bottom", fill="x")
        self._expedition_tabs = ttk.Notebook(wrap, style="Poke.TNotebook")
        self._expedition_tabs.pack(fill="both", expand=True)
        self._expedition_destinations = tk.Frame(self._expedition_tabs, bg=PANEL)
        self._expedition_rest_tab = tk.Frame(self._expedition_tabs, bg=PANEL)
        self._expedition_history_tab = tk.Frame(self._expedition_tabs, bg=PANEL)
        self._expedition_tabs.add(self._expedition_destinations, text=t("expedition.destinations"))
        self._expedition_tabs.add(self._expedition_rest_tab, text=t("expedition.resting", count=0))
        self._expedition_tabs.add(self._expedition_history_tab, text=t("expedition.history"))
        inner = self._scrollable(self._expedition_destinations)
        self._expedition_rest_content = self._scrollable(self._expedition_rest_tab)
        self._expedition_history_content = self._scrollable(self._expedition_history_tab)
        self._expedition_rest_rows = {}
        self._expedition_rest_snapshot = None
        self._expedition_history_snapshot = None
        self._expedition_tabs.bind("<<NotebookTabChanged>>", lambda _event: self._refresh_expedition_status())
        self._expedition_cards = {}
        for key, destination in EXPEDITION_DESTINATIONS.items():
            card = ExpeditionCard(inner, key, destination,
                                  lambda identity, key=key: self._send_expedition(key, identity),
                                  lambda key=key: self._claim_expedition(key))
            card.pack(fill="x", pady=3, padx=(0, 4))
            self._expedition_cards[key] = card
        self._refresh_expeditions()

    def _expedition_name(self, sid: int, shiny: bool) -> str:
        name = self.app.dex.species[sid].name(self.app.config.language)
        return t("expedition.shiny_name", name=name) if shiny else name

    def _refresh_expeditions(self) -> None:
        self._expedition_title.configure(text=t("expedition.title"))
        self._expedition_hint.configure(text=t("expedition.hint"))
        self._expedition_tabs.tab(self._expedition_destinations, text=t("expedition.destinations"))
        self._expedition_tabs.tab(self._expedition_history_tab, text=t("expedition.history"))
        game = self.app.game
        self._expedition_cooling = game.expedition_resting_species()
        roster = sorted(
            (f"{self._expedition_name(*identity)} · {tr_rarity(grade)}", identity, RARITY_ORDER.index(grade))
            for identity, grade in game.expedition_candidates().items()
        )
        for key, card in self._expedition_cards.items():
            destination = EXPEDITION_DESTINATIONS[key]
            card.title.configure(text=t("expedition." + key))
            card.details.configure(text=t("expedition.details", rarity=tr_rarity(destination.rarity),
                                          minutes=destination.minutes, points=destination.points,
                                          bonus=destination.shiny_bonus))
            trip = game.expeditions.get(key)
            pending = game.expedition_reward_pending(key)
            card.show_traveler(self.app, (trip.species_id, trip.shiny) if trip else None)
            minimum = RARITY_ORDER.index(destination.rarity)
            options = [] if trip or pending else [
                (identity, label) for label, identity, grade in roster if grade >= minimum
            ]
            card.set_options(options, trip is not None, pending)

    def _refresh_expedition_status(self) -> None:
        game = self.app.game
        resting = game.expedition_resting_species()
        if resting != self._expedition_cooling:
            self._refresh_expeditions()
        self._refresh_expedition_rest(resting)
        self._refresh_expedition_history()
        for key, card in self._expedition_cards.items():
            trip = game.expeditions.get(key)
            report = game.expedition_returns.get(key)
            status = ""
            if trip:
                mode = "paused" if self.app.office_paused else "active"
                status = t("expedition." + mode, name=self._expedition_name(trip.species_id, trip.shiny),
                           left=_duration(ceil(game.expedition_remaining(key))))
            elif report:
                key_for_status = "expedition.last" if report.claimed else "expedition.last_pending"
                status = t(key_for_status, points=report.points,
                           name=self._expedition_name(report.species_id, report.shiny))
                remaining = game.expedition_rest_remaining(report.species_id)
                if remaining:
                    status += "\n" + t("expedition.rest", left=_rest_duration(remaining))
            card.status.configure(text=status)

    def _refresh_expedition_rest(self, resting: set[int]) -> None:
        tabs = self._expedition_tabs
        tabs.tab(self._expedition_rest_tab, text=t("expedition.resting", count=len(resting)))
        if tabs.select() != str(self._expedition_rest_tab):
            return
        game = self.app.game
        roster = sorted(
            (game.expedition_cooldowns[sid], sid, tuple(shiny for shiny in (False, True)
                                                      if sid in game.graduated[shiny]))
            for sid in resting
        )
        snapshot = self.app.config.language, roster
        if snapshot != self._expedition_rest_snapshot:
            content = self._expedition_rest_content
            self._clear(content)
            self._expedition_rest_rows.clear()
            if not roster:
                tk.Label(content, text=t("expedition.rest_empty"), bg=PANEL, fg=MUTED,
                         font=("Segoe UI", 9)).pack(pady=16)
            for until, sid, variants in roster:
                row = ExpeditionRestRow(content, self.app, sid, variants, until)
                row.pack(fill="x", padx=(0, 4), pady=3)
                self._expedition_rest_rows[sid] = row
            self._expedition_rest_snapshot = snapshot

        for sid, row in self._expedition_rest_rows.items():
            row.update_time(game.expedition_rest_remaining(sid))

    def _send_expedition(self, key: str, identity: tuple[int, bool] | None) -> None:
        if identity is None:
            return
        try:
            sent = self.app.game.start_expedition(key, *identity)
        except OSError:
            self._expedition_message.configure(text=t("save.retry"), fg="#e0665f")
            return
        self._expedition_message.configure(text="")
        if sent:
            self.render([])

    def _claim_expedition(self, key: str) -> None:
        try:
            message = self.app.game.claim_expedition_reward(key)
        except OSError:
            self._expedition_message.configure(text=t("save.retry"), fg="#e0665f")
            return
        if message:
            self.render([])
            self._expedition_message.configure(text=message, fg=GOOD)

    def _refresh_expedition_history(self) -> None:
        if self._expedition_tabs.select() != str(self._expedition_history_tab):
            return
        history = tuple(self.app.game.expedition_history)
        snapshot = self.app.config.language, history
        if snapshot == self._expedition_history_snapshot:
            return
        self._expedition_history_snapshot = snapshot
        content = self._expedition_history_content
        self._clear(content)
        if not history:
            tk.Label(content, text=t("expedition.history_empty"), bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 9)).pack(pady=16)
        for key, report in history:
            bg = "#23262f"
            row = tk.Frame(content, bg=bg)
            row.pack(fill="x", padx=(0, 4), pady=3)
            portrait = self.app.still(report.species_id, report.shiny, 40)
            if portrait is not None:
                photo = ImageTk.PhotoImage(portrait, master=row)
                icon = tk.Label(row, image=photo, bg=bg, borderwidth=0)
                icon.image = photo
                icon.pack(side="left", padx=(8, 10), pady=8)
            body = tk.Frame(row, bg=bg)
            body.pack(side="left", fill="x", expand=True, padx=(6, 8), pady=6)
            name = self._expedition_name(report.species_id, report.shiny)
            tk.Label(body, text=f"{name} · {t('expedition.' + key)}", anchor="w", bg=bg, fg=FG,
                     font=("Segoe UI", 9, "bold")).pack(fill="x")
            state = "expedition.history_claimed" if report.claimed else "expedition.history_pending"
            tk.Label(body, text=t(state, points=report.points), anchor="w", bg=bg,
                     fg=MUTED if report.claimed else ACCENT, font=("Segoe UI", 9)).pack(fill="x")
            if report.returned_at is not None and (when := _local_timestamp(report.returned_at)):
                tk.Label(body, text=when, anchor="w", bg=bg, fg=MUTED,
                         font=("Segoe UI", 8)).pack(fill="x")

    # ---- pokedex / bag / shop --------------------------------------

    def _clear(self, frame: tk.Frame) -> None:
        for child in frame.winfo_children():
            child.destroy()

    def _sprite_label(self, parent, species_id, shiny, size, bg):
        """A static sprite, or a dim placeholder while it is still downloading."""
        img = self.app.still(species_id, shiny, size)
        if img is None:
            box = tk.Frame(parent, width=size, height=size, bg=bg)
            tk.Label(box, text="…", bg=bg, fg=MUTED).place(relx=0.5, rely=0.5, anchor="center")
            return box
        photo = ImageTk.PhotoImage(img)
        self._images.append(photo)          # Tk does not own PhotoImage refs
        return tk.Label(parent, image=photo, bg=bg, bd=0, highlightthickness=0)

    def _icon_label(self, parent, item_key, size, bg):
        img = self.app.item_image(item_key, size)
        if img is None:
            return tk.Frame(parent, width=size, height=size, bg=bg)
        photo = ImageTk.PhotoImage(img)
        self._images.append(photo)
        return tk.Label(parent, image=photo, bg=bg, bd=0, highlightthickness=0)

    def _scrollable(self, parent):
        """A vertically scrollable panel; returns the frame to fill."""
        canvas = tk.Canvas(parent, bg=PANEL, highlightthickness=0, bd=0)
        bar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=PANEL)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def on_config(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(window, width=canvas.winfo_width())
            # Only show the scrollbar when there is something to scroll to.
            if inner.winfo_reqheight() > canvas.winfo_height():
                if not bar.winfo_ismapped():
                    bar.pack(side="right", fill="y")
            elif bar.winfo_ismapped():
                bar.pack_forget()

        inner.bind("<Configure>", on_config)
        canvas.bind("<Configure>", on_config)
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)

        def wheel(event):
            canvas.yview_scroll(-1 * (event.delta // 120), "units")

        # Bind the wheel only while the pointer is over this panel. A global
        # bind_all would also fire for other panels — including destroyed ones
        # left over from a previous render.
        def grab_wheel(_e=None):
            canvas.bind_all("<MouseWheel>", wheel)

        def release_wheel(_e=None):
            canvas.unbind_all("<MouseWheel>")

        for w in (canvas, inner):
            w.bind("<Enter>", grab_wheel)
            w.bind("<Leave>", release_wheel)
        canvas.bind("<Destroy>", release_wheel)
        return inner

    def _rarity_chips(self, parent, counts) -> None:
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=(6, 10))
        for key in reversed(RARITY_ORDER):
            tk.Label(row, text="\u25cf", bg=PANEL, fg=RARITY_COLOR[key],
                     font=("Segoe UI", 8)).pack(side="left")
            tk.Label(row, text=f"{tr_rarity(key)} {counts.get(key, 0)}", bg=PANEL,
                     fg=MUTED, font=("Segoe UI", 8)).pack(side="left", padx=(2, 12))

    # ---- pokedex ---------------------------------------------------

    @_game_view
    def _render_pokedex(self) -> None:
        self._clear(self.dex_tab)
        wrap = tk.Frame(self.dex_tab, bg=PANEL)
        wrap.pack(fill="both", expand=True, padx=12, pady=12)

        switch = tk.Frame(wrap, bg=PANEL)
        switch.pack(fill="x")
        for view, key in (("dex", "dex.tab.dex"), ("log", "dex.tab.log")):
            selected = self._dex_view == view
            tk.Button(
                switch, text=t(key), command=lambda v=view: self._set_dex_view(v),
                bg=ACCENT if selected else "#2a2d38",
                fg="#1a1a1a" if selected else MUTED,
                relief="flat", cursor="hand2", font=("Segoe UI", 9, "bold"),
                padx=12, pady=3,
            ).pack(side="left", padx=(0, 6))

        body = tk.Frame(wrap, bg=PANEL)
        body.pack(fill="both", expand=True, pady=(10, 0))
        if self._dex_view == "dex":
            self._render_dex_grid(body)
        else:
            self._render_catch_log(body)

    def _set_dex_view(self, view: str) -> None:
        self._dex_view = view
        self._render_pokedex()

    def _render_dex_grid(self, parent) -> None:
        app, game = self.app, self.app.game
        owned = sorted(game.pokedex)

        counts = {}
        for sid in owned:
            sp = app.dex.species.get(sid)
            if sp:
                counts[sp.rarity] = counts.get(sp.rarity, 0) + 1

        tk.Label(parent, text=t("dex.title", n=len(owned)), bg=PANEL, fg=FG,
                 font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x")
        self._rarity_chips(parent, counts)

        if owned:
            bar = tk.Frame(parent, bg=PANEL)
            bar.pack(fill="x", pady=(0, 8))
            pinned = app.config.pinned_species
            sp = app.dex.species.get(pinned) if pinned else None
            if sp is not None:
                tk.Label(bar, text=t("dex.pin.current",
                                     name=sp.name(app.config.language)),
                         bg=PANEL, fg=ACCENT, font=("Segoe UI", 8, "bold"),
                         anchor="w").pack(side="left")
                tk.Button(bar, text=t("dex.pin.clear"),
                          command=lambda: self._toggle_pin(pinned),
                          bg="#2a2d38", fg=MUTED, relief="flat", cursor="hand2",
                          font=("Segoe UI", 8), padx=8).pack(side="right")
            else:
                tk.Label(bar, text=t("dex.pin.hint"), bg=PANEL, fg=MUTED,
                         font=("Segoe UI", 8), anchor="w").pack(side="left")

        if not owned:
            tk.Label(parent, text=t("dex.empty"), bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 9), anchor="w").pack(fill="x")
            return

        pages = max(1, (len(owned) + DEX_PER_PAGE - 1) // DEX_PER_PAGE)
        self._dex_page = max(0, min(self._dex_page, pages - 1))
        page = owned[self._dex_page * DEX_PER_PAGE:(self._dex_page + 1) * DEX_PER_PAGE]

        # Pager first and anchored to the bottom, so a short window can never
        # push it out of reach; the grid then scrolls in whatever space is left.
        if pages > 1:
            nav = tk.Frame(parent, bg=PANEL)
            nav.pack(fill="x", side="bottom", pady=(8, 0))
            pager = tk.Frame(nav, bg=PANEL)
            pager.pack(anchor="center")
            _action(pager, "‹", lambda: self._turn_page(-1),
                    enabled=self._dex_page > 0).pack(side="left")
            tk.Label(pager, text=f"{self._dex_page + 1} / {pages}", bg=PANEL,
                     fg=MUTED, font=("Segoe UI", 9), width=8).pack(side="left")
            _action(pager, "›", lambda: self._turn_page(1),
                    enabled=self._dex_page < pages - 1).pack(side="left")

        holder = tk.Frame(parent, bg=PANEL)
        holder.pack(fill="both", expand=True)
        grid = self._scrollable(holder)
        for c in range(DEX_COLS):
            grid.columnconfigure(c, weight=1, uniform="dex")

        pinned = app.config.pinned_species
        for n, sid in enumerate(page):
            sp = app.dex.species.get(sid)
            if not sp:
                continue
            rec = game.pokedex[sid]
            shiny = bool(rec.get("shiny"))
            is_pinned = sid == pinned
            bg = "#2c2a22" if is_pinned else "#23262f"
            cell = tk.Frame(grid, bg=bg, highlightthickness=2 if is_pinned else 1,
                            highlightbackground=ACCENT if is_pinned
                            else RARITY_COLOR.get(sp.rarity, MUTED))
            cell.grid(row=n // DEX_COLS, column=n % DEX_COLS, padx=3, pady=3, sticky="nsew")
            self._sprite_label(cell, sid, shiny, DEX_SPRITE, bg).pack(pady=(6, 0))
            tk.Label(cell, text=("\u2605 " if is_pinned else "") + f"#{sid}", bg=bg,
                     fg=ACCENT if is_pinned else MUTED,
                     font=("Segoe UI", 7)).pack()
            tk.Label(cell, text=sp.name(app.config.language) + (" \u2728" if shiny else ""),
                     bg=bg, fg=FG, font=("Segoe UI", 8), wraplength=88).pack(pady=(0, 6))
            # The whole cell is the hit target, children included.
            for w in (cell, *cell.winfo_children()):
                w.bind("<Button-1>", lambda _e, i=sid: self._toggle_pin(i))
                w.configure(cursor="hand2")

    def _toggle_pin(self, species_id: int) -> None:
        """Pin this species to the tray/pet, or unpin it if already pinned."""
        cfg = self.app.config
        cfg.pinned_species = 0 if cfg.pinned_species == species_id else species_id
        cfg.save(self.app.config_path)
        self.render([])
        self.event_generate("<<PinChanged>>")

    def _turn_page(self, delta: int) -> None:
        self._dex_page += delta
        self._render_pokedex()

    # ---- catch log -------------------------------------------------

    def _render_catch_log(self, parent) -> None:
        app, game = self.app, self.app.game
        log = game.catch_log

        counts = {}
        for rec in log:
            r = rec.get("rarity", "Common")
            counts[r] = counts.get(r, 0) + 1
        tk.Label(parent, text=t("dex.log.title", n=len(log)), bg=PANEL, fg=FG,
                 font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x")
        self._rarity_chips(parent, counts)

        holder = tk.Frame(parent, bg=PANEL)
        holder.pack(fill="both", expand=True)
        inner = self._scrollable(holder)

        c = game.companion
        if c.hatched and c.path and not game.collection_complete:
            self._log_row(inner, c.path, c.stage, c.shiny, c.rarity, c.nature,
                          raising=True)
        for rec in log[:60]:
            self._log_row(inner, rec.get("line", []), len(rec.get("line", [])) - 1,
                          bool(rec.get("shiny")), rec.get("rarity", "Common"),
                          rec.get("nature", ""), caught_at=rec.get("caught_at", ""))
        if not log and not (c.hatched and c.path):
            tk.Label(inner, text=t("dex.log.empty"), bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=6)

    def _log_row(self, parent, line, upto, shiny, rarity, nature,
                 raising: bool = False, caught_at: str = "") -> None:
        app = self.app
        card = tk.Frame(parent, bg="#23262f")
        card.pack(fill="x", pady=3, padx=(0, 6))

        head = tk.Frame(card, bg="#23262f")
        head.pack(fill="x", padx=8, pady=(6, 0))
        tk.Label(head, text=tr_rarity(rarity), bg=RARITY_COLOR.get(rarity, MUTED),
                 fg="#1a1a1a", font=("Segoe UI", 7, "bold"), padx=5).pack(side="left")
        if raising:
            tk.Label(head, text=t("dex.raising"), bg=ACCENT, fg="#1a1a1a",
                     font=("Segoe UI", 7, "bold"), padx=5).pack(side="left", padx=(4, 0))
        tk.Label(head, text=tr_nature(nature), bg="#23262f", fg=MUTED,
                 font=("Segoe UI", 8)).pack(side="right")

        strip = tk.Frame(card, bg="#23262f")
        strip.pack(fill="x", padx=8, pady=(4, 6))
        for idx, sid in enumerate(line):
            sp = app.dex.species.get(sid)
            if not sp:
                continue
            if idx:
                tk.Label(strip, text="\u2192", bg="#23262f", fg=MUTED,
                         font=("Segoe UI", 9)).pack(side="left", padx=2)
            col = tk.Frame(strip, bg="#23262f")
            col.pack(side="left")
            # Stages not yet reached are shown, but dimmed by the name colour.
            reached = idx <= upto
            self._sprite_label(col, sid, shiny and reached, LOG_SPRITE, "#23262f").pack()
            tk.Label(col, text=sp.name(app.config.language), bg="#23262f",
                     fg=FG if reached else "#555a68", font=("Segoe UI", 7)).pack()
        if caught_at:
            tk.Label(strip, text=caught_at[:10], bg="#23262f", fg="#555a68",
                     font=("Segoe UI", 7)).pack(side="right")

    # ---- bag -------------------------------------------------------

    @_game_view
    def _render_bag(self) -> None:
        game = self.app.game
        self._clear(self.bag_tab)
        wrap = tk.Frame(self.bag_tab, bg=PANEL)
        wrap.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(wrap, text=t("bag.title"), bg=PANEL, fg=FG,
                 font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x", pady=(0, 10))
        self.bag_msg = tk.Label(wrap, text="", bg=PANEL, fg=GOOD,
                                font=("Segoe UI", 9), anchor="w", wraplength=380,
                                justify="left")

        def use(fn):
            def handler():
                try:
                    msg = fn() or t("bag.none")
                except OSError:
                    self.bag_msg.configure(text=t("save.retry"), fg="#e0665f")
                    return
                # Successful candy use already queues a refresh for every surface.
                if not isinstance(msg, CandyUseNotice):
                    self.render([])
                self.bag_msg.configure(text=msg)
            return handler

        for key, count, desc, fn in (
            ("rare_candy", game.candies, t("item.rare_candy.office.desc"), self.app.use_candy),
            ("mint", game.mints, t("item.mint.desc"), game.use_mint),
            ("incense", game.incense, t("item.incense.bag.desc"), game.use_incense),
        ):
            row = tk.Frame(wrap, bg="#2a2d38")
            row.pack(fill="x", pady=4)
            self._icon_label(row, key, ITEM_ICON, "#2a2d38").pack(
                side="left", padx=(10, 8), pady=8)
            text = tk.Frame(row, bg="#2a2d38")
            text.pack(side="left", fill="x", expand=True)
            tk.Label(text, text=f"{t('item.' + key)}  \u00d7{count}", bg="#2a2d38",
                     fg=FG, font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x")
            tk.Label(text, text=desc, bg="#2a2d38", fg=MUTED,
                     font=("Segoe UI", 8), anchor="w", justify="left",
                     wraplength=270 if key == "incense" else 0).pack(fill="x")
            enabled = bool(count) and not (key == "rare_candy" and game.collection_complete)
            _action(row, t("bag.use"), use(fn), enabled=enabled).pack(
                side="right", padx=10, pady=6)

        incense = tk.Frame(wrap, bg=PANEL)
        incense.pack(fill="x", pady=(4, 0))
        self._incense_status = tk.Label(incense, bg=PANEL, fg=MUTED, font=("Segoe UI", 9))
        self._incense_status.pack(side="left")
        self._incense_toggle = _action(incense, "", self.toggle_incense, enabled=True)
        self._incense_toggle.configure(width=0, padx=8)
        self._incense_toggle.pack(side="right")
        self.refresh_incense()

        charm = tk.Frame(wrap, bg=PANEL)
        charm.pack(fill="x", pady=(12, 0))
        self._icon_label(charm, "shiny_charm", 24, PANEL).pack(side="left", padx=(0, 6))
        tk.Label(charm, text=t("bag.charms", n=game.shiny_charms,
                               chance=f"{100 / game.shiny_odds():.1f}"),
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 9), anchor="w").pack(side="left")
        bell = tk.Frame(wrap, bg=PANEL)
        bell.pack(fill="x", pady=(10, 0))
        self._icon_label(bell, "soothe_bell", 24, PANEL).pack(side="left", padx=(0, 6))
        low, high = game.gift_wait_range
        tk.Label(bell, text=t("bag.soothe_bell", n=game.soothe_bell,
                              low=_duration(low), high=_duration(high)), bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 9), anchor="w", wraplength=340,
                 justify="left").pack(side="left")
        self.bag_msg.pack(fill="x", pady=(10, 0))

    def refresh_incense(self) -> None:
        if self._incense_status is None:
            return
        active, left = self.app.game.incense_status()
        label = "incense.running" if active else "incense.paused" if left else "incense.empty"
        self._incense_status.configure(text=t(label, left=_duration(ceil(left))))
        self._incense_toggle.configure(text=t("incense.off" if active else "incense.on"),
                                       state="normal" if left else "disabled",
                                       bg=ACCENT if left else "#33363f")

    def toggle_incense(self) -> None:
        try:
            self.app.game.toggle_incense()
        except OSError:
            if self._incense_status is not None:
                self.bag_msg.configure(text=t("save.retry"), fg="#e0665f")
            return
        self.refresh_incense()
        self.event_generate("<<IncenseChanged>>")

    # ---- shop ------------------------------------------------------

    @_game_view
    def _render_shop(self) -> None:
        game = self.app.game
        self._clear(self.shop_tab)
        wrap = tk.Frame(self.shop_tab, bg=PANEL)
        wrap.pack(fill="both", expand=True, padx=12, pady=12)

        balance = game.currency(self.app.game_total)
        tk.Label(wrap, text=t("office.shop", balance=format(balance, ",")),
                 bg=PANEL, fg=FG, font=("Segoe UI", 11, "bold"), anchor="w").pack(
            fill="x", pady=(0, 8))
        self.shop_msg = tk.Label(wrap, text="", bg=PANEL, fg=GOOD,
                                 font=("Segoe UI", 9), anchor="w", wraplength=380,
                                 justify="left")
        self.shop_msg.pack(fill="x", side="bottom", pady=(8, 0))

        inner = self._scrollable(wrap)

        for item, price in game.shop_prices.items():
            row = tk.Frame(inner, bg="#2a2d38")
            row.pack(fill="x", pady=3, padx=(0, 6))
            self._icon_label(row, item, ITEM_ICON, "#2a2d38").pack(
                side="left", padx=(10, 8), pady=8)
            text = tk.Frame(row, bg="#2a2d38")
            text.pack(side="left", fill="x", expand=True)
            title = tk.Frame(text, bg="#2a2d38")
            title.pack(fill="x")
            tk.Label(title, text=t(f"item.{item}"), bg="#2a2d38", fg=FG,
                     font=("Segoe UI", 10, "bold")).pack(side="left")
            floor = EGG_FLOORS.get(item)
            if floor:
                tk.Label(title, text=tr_rarity(floor[0]),
                         bg=RARITY_COLOR.get(floor[0], MUTED), fg="#1a1a1a",
                         font=("Segoe UI", 7, "bold"), padx=4).pack(side="left", padx=6)
            desc_key = ("item.rare_candy.office.desc" if item == "rare_candy"
                        else f"item.{item}.desc")
            tk.Label(text, text=t("office.price", desc=t(desc_key),
                                  price=format(price, ",")),
                     bg="#2a2d38", fg=MUTED, font=("Segoe UI", 8), anchor="w",
                     wraplength=250, justify="left").pack(fill="x")
            capped = ((item == "shiny_charm" and game.shiny_charms >= MAX_SHINY_CHARMS)
                      or (item == "soothe_bell" and game.soothe_bell >= MAX_SOOTHE_BELLS)
                      or (item in EGG_FLOORS and not game.can_buy_egg(item)))
            _action(row, t("shop.buy"), lambda item=item: self._buy_item(item),
                    enabled=balance >= price and not capped).pack(
                side="right", padx=10, pady=8)

    def _buy_item(self, item: str) -> None:
        if item not in EGG_FLOORS:
            self._complete_purchase(item)
            return
        if self._egg_dialog is not None and self._egg_dialog.winfo_exists():
            self._egg_dialog.lift()
            return
        game = self.app.game
        companion = game.companion
        price = t("office.price", desc=t(f"item.{item}"),
                  price=format(game.shop_prices[item], ","))
        dialog = EggPurchaseDialog(
            self, price, lambda: self._complete_purchase(item, expected_companion=companion),
        )
        self._egg_dialog = dialog

        def forget(event):
            if event.widget is dialog:
                self._egg_dialog = None

        dialog.bind("<Destroy>", forget)

    def _complete_purchase(self, item: str, *, expected_companion=None) -> None:
        try:
            msg = self.app.game.buy(item, self.app.game_total, expected_companion=expected_companion)
        except OSError:
            self.shop_msg.configure(text=t("save.retry"), fg="#e0665f")
            return
        self.render([])
        self.shop_msg.configure(text=msg)


class _Bubble(tk.Toplevel):
    """A small popup anchored to the pet."""

    def __init__(self, master, text: str, accent: bool = False) -> None:
        super().__init__(master)
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        border = ACCENT if accent else "#3a3e4a"
        frame = tk.Frame(self, bg=border)
        frame.pack()
        self.label = tk.Label(
            frame, text=text, bg=BG, fg=ACCENT if accent else FG,
            font=("Segoe UI", 9, "bold" if accent else "normal"),
            justify="left", anchor="w", padx=10, pady=6, wraplength=320 if accent else 0,
        )
        self.label.pack(padx=1, pady=1)
        self.update_idletasks()
        prevent_activation(self)
        self.deiconify()
        self.update_idletasks()


class FloatingPet(tk.Toplevel):
    """Frameless always-on-top companion."""

    def __init__(self, master, app, on_click, on_open_settings=None,
                 on_quit=None, on_context_menu=None, menu_is_open=None) -> None:
        super().__init__(master)
        self.app = app
        self.on_click = on_click
        self.on_open_settings = on_open_settings
        self.on_quit = on_quit
        self.on_context_menu = on_context_menu
        self.menu_is_open = menu_is_open or (lambda: False)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#010101")
        self.attributes("-transparentcolor", "#010101")

        self.sprite = SpriteView(self, app, size=app.config.pet_size,
                                 matte=True, walking=True, bg="#010101")
        self.sprite.pack()
        self._gift_image: Image.Image | None = None
        self._gift_pressed = False

        self._drag = (0, 0)
        self._moved = False
        self._hover: _Bubble | None = None
        self._alert: _Bubble | None = None
        self._countdown: _Bubble | None = None
        self._alert_job = None
        self._return_alert = ""
        self._hover_job = None
        self._pressed = False
        self._roam_mode = ROAM_OFF
        self._roam_goal: tuple[int, int] | None = None
        self._roam_target: tuple[int, int] | None = None
        self._roam_after = 0.0
        self._roam_until = 0.0
        self._walk_job = None

        for widget in (self, self.sprite):
            widget.bind("<Button-1>", self._press)
            widget.bind("<B1-Motion>", self._move)
            widget.bind("<ButtonRelease-1>", self._release)
            widget.bind("<Button-3>", self._menu)
            widget.bind("<Enter>", self._hover_in)
            widget.bind("<Leave>", self._hover_out)
        self.bind("<Configure>", self._place_bubbles)

        self.update_idletasks()
        self._restore_position()

    # ---- placement -------------------------------------------------

    def _place_bubbles(self, event=None) -> None:
        if event is not None and event.widget is not self:
            return
        bubbles = [bubble for bubble in (self._countdown, self._alert, self._hover)
                   if bubble is not None]
        if not bubbles or (window := pet_window(self)) is None:
            return
        _, rect, work = window
        height = sum(bubble.winfo_reqheight() + 6 for bubble in bubbles)
        above_space = rect.top - work.top
        below_space = work.bottom - rect.bottom
        below = above_space < height and below_space > above_space
        edge = rect.bottom if below else rect.top
        for bubble in bubbles:
            width, height = bubble.winfo_reqwidth(), bubble.winfo_reqheight()
            centered = (rect.left + rect.right - width) // 2
            x = max(work.left, min(centered, work.right - width))
            y = edge + 6 if below else edge - height - 6
            y = max(work.top, min(y, work.bottom - height))
            if (position := pet_window(bubble)) is not None:
                hwnd, current, _ = position
                if (x, y) != (current.left, current.top):
                    move_window(hwnd, x, y)
            edge = y + height if below else y

    def _restore_position(self) -> None:
        """Put the pet back where it was dragged, or in a default corner."""
        cfg = self.app.config
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = max(self.winfo_reqwidth(), cfg.pet_size)
        h = max(self.winfo_reqheight(), cfg.pet_size)
        if cfg.pet_x >= 0 and cfg.pet_y >= 0:
            x, y = cfg.pet_x, cfg.pet_y
        else:
            x, y = sw - cfg.pet_size - 60, 80
        # Keep it reachable if the display layout changed since it was saved.
        x = max(0, min(x, sw - w))
        y = max(0, min(y, sh - h))
        self.geometry(f"+{x}+{y}")

    def _rest_from_roaming(self, now: float) -> None:
        self._roam_target = None
        self._roam_after = now + uniform(12, 20)

    def _roam_ready(self, now: float) -> bool:
        if self._roam_mode == ROAM_OFF:
            return False
        if self._roam_target is not None and now >= self._roam_until:
            self._rest_from_roaming(now)
        return (now >= self._roam_after and self.winfo_viewable()
                and not (self._pressed or self.menu_is_open() or self._alert))

    def _tick_walking(self) -> None:
        self._walk_job = None
        if self._roam_mode == ROAM_OFF:
            return
        now = monotonic()
        if self._roam_ready(now):
            window = pet_window(self)
            if window is not None:
                hwnd, rect, work = window
                if not pointer_over(rect) and self._roam_step(hwnd, rect, work, now):
                    self._walk_job = self.after(120, self._tick_walking)
                    return
        self.sprite.resume_idle()
        self._walk_job = self.after(250, self._tick_walking)

    def _cancel_walking(self) -> None:
        if self._walk_job is not None:
            self.after_cancel(self._walk_job)
            self._walk_job = None
        self.sprite.resume_idle()

    def _walk_bounds(self, rect, work) -> tuple[int, int, int, int]:
        right = max(work.left, work.right - (rect.right - rect.left))
        bottom = max(work.top, work.bottom - (rect.bottom - rect.top))
        if self._roam_mode == ROAM_TASKBAR:
            y = max(work.top, bottom - 8)
            return work.left, y, right, y
        return work.left, work.top, right, bottom

    def _align_to_taskbar(self) -> None:
        self.update_idletasks()
        window = pet_window(self)
        if window is not None:
            hwnd, rect, work = window
            left, y, right, _ = self._walk_bounds(rect, work)
            x = max(left, min(rect.left, right))
            if (x, y) != (rect.left, rect.top):
                move_window(hwnd, x, y)

    def _roam_step(self, hwnd, rect, work, now: float) -> bool:
        left, top, right, bottom = self._walk_bounds(rect, work)
        x, y = rect.left, rect.top
        if not (left <= x <= right and top <= y <= bottom):
            move_window(hwnd, max(left, min(x, right)), max(top, min(y, bottom)))
            self._roam_goal = self._roam_target = None
            return False
        if self._roam_target is None:
            if self._roam_goal is None or self._roam_goal == (x, y):
                self._roam_goal = (randint(left, right), randint(top, bottom))
            goal_x, goal_y = self._roam_goal
            goal_x = max(left, min(goal_x, right))
            goal_y = max(top, min(goal_y, bottom))
            self._roam_goal = (goal_x, goal_y)
            dx, dy = goal_x - x, goal_y - y
            fraction = 28 / max(28, hypot(dx, dy))
            self._roam_target = (x + round(dx * fraction), y + round(dy * fraction))
            self._roam_until = now + 2.5
        target_x, target_y = self._roam_target
        dx = max(left, min(target_x, right)) - x
        dy = max(top, min(target_y, bottom)) - y
        distance = hypot(dx, dy)
        step = 4
        if distance <= step:
            self._rest_from_roaming(now)
        if distance and self.sprite.advance_walk():
            fraction = step / max(step, distance)
            if move_window(hwnd, x + round(dx * fraction), y + round(dy * fraction)):
                return True
        self._rest_from_roaming(now)
        return False

    # ---- pointer ---------------------------------------------------

    def _hits_gift(self, event) -> bool:
        return self.sprite.hits_overlay(event.x_root - self.sprite.winfo_rootx(),
                                        event.y_root - self.sprite.winfo_rooty())

    def _press(self, event) -> None:
        self._pressed = True
        self._gift_pressed = self._hits_gift(event)
        if self._gift_pressed:
            self._close_hover()
            return "break"
        self._drag = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y())
        self._moved = False
        self._close_hover()

    def _move(self, event) -> None:
        if self._gift_pressed:
            return "break"
        self._moved = True
        x = event.x_root - self._drag[0]
        y = event.y_root - self._drag[1]
        self.geometry(f"+{x}+{y}")

    def _release(self, event) -> None:
        self._pressed = False
        if self._gift_pressed:
            self._gift_pressed = False
            if event is not None and self._hits_gift(event):
                self.app.claim_gift()
            return "break"
        self._rest_from_roaming(monotonic())
        if not self._moved:
            self.on_click()
            return
        cfg = self.app.config
        self._roam_goal = None
        if self._roam_mode == ROAM_TASKBAR:
            self._align_to_taskbar()
            self.update_idletasks()
        cfg.pet_x, cfg.pet_y = self.winfo_x(), self.winfo_y()
        cfg.save(self.app.config_path)

    # ---- hover readout ---------------------------------------------

    def _hover_in(self, _event=None) -> None:
        if self.menu_is_open():
            return
        if self._hover_job:
            self.after_cancel(self._hover_job)
        self._hover_job = self.after(350, self._show_hover)

    def _hover_out(self, _event=None) -> None:
        if self._hover_job:
            self.after_cancel(self._hover_job)
            self._hover_job = None
        self._close_hover()

    def _show_hover(self) -> None:
        self._hover_job = None
        self._close_hover()
        if not self.app.ready or self._return_alert:
            return
        try:
            self._hover = _Bubble(self, self._hover_text())
            self._place_bubbles()
        except tk.TclError:
            self._hover = None

    def _hover_text(self) -> str:
        app = self.app
        return t("office.balance", balance=app.game.currency(app.game_total))

    def _close_hover(self) -> None:
        if self._hover is not None:
            try:
                self._hover.destroy()
            except tk.TclError:
                pass
            self._hover = None

    # ---- right-click menu ------------------------------------------

    def _menu(self, event) -> str:
        self._hover_out()
        self._pressed = self._gift_pressed = False
        # The tray thread owns the Windows popup and queues its selected action.
        # A Tk popup here used to destroy its own widgets inside tk_popup,
        # triggering a fatal Tcl abort when hiding the pet or redrawing the UI.
        if self.on_context_menu is not None:
            self.on_context_menu()
        return "break"

    def refresh_work_countdown(self, now: datetime | None = None) -> None:
        text = self.app.config.work_countdown_text(now if now is not None else datetime.now())
        if not text:
            if self._countdown is not None:
                self._countdown.destroy()
                self._countdown = None
                self._place_bubbles()
            return
        if self._countdown is None:
            self._countdown = _Bubble(self, text)
            self._countdown.bind("<Button-3>", self._menu)
        elif self._countdown.label.cget("text") != text:
            self._countdown.label.configure(text=text)
            self._countdown.update_idletasks()
        self._place_bubbles()

    # ---- alerts ----------------------------------------------------

    def say(self, text: str, seconds: int = 8, *, expedition_return: bool = False) -> None:
        """Show a speech bubble above the pet for a while."""
        if self._return_alert:
            if not expedition_return:
                return
            text = self._return_alert + "\n" + text
        if expedition_return:
            self._hover_out()
        self._clear_alert()
        try:
            self._alert = _Bubble(self, text, accent=True)
            self._place_bubbles()
        except tk.TclError:
            self._alert = None
            return
        self._return_alert = text if expedition_return else ""
        self._alert_job = self.after(seconds * 1000, self._clear_alert)

    def _clear_alert(self) -> None:
        self._return_alert = ""
        if self._alert_job:
            self.after_cancel(self._alert_job)
            self._alert_job = None
        if self._alert is not None:
            try:
                self._alert.destroy()
            except tk.TclError:
                pass
            self._alert = None
            self._place_bubbles()

    def destroy(self) -> None:
        self._cancel_walking()
        if self._hover_job is not None:
            self.after_cancel(self._hover_job)
        self.sprite.stop()
        self._close_hover()
        self._clear_alert()
        if self._countdown is not None:
            self._countdown.destroy()
            self._countdown = None
        super().destroy()

    # ---- render ----------------------------------------------------

    @_game_view
    def render(self) -> None:
        mode = self.app.config.pet_roam_mode
        if mode != self._roam_mode:
            self._cancel_walking()
            self._roam_mode = mode
            self._roam_goal = self._roam_target = None
            self._roam_after = monotonic()
            if mode != ROAM_OFF:
                self._walk_job = self.after(250, self._tick_walking)
        size = self.app.config.pet_size
        if self.sprite.size != size:
            self.sprite.size = size
            self.sprite._key = None
        self._gift_image = None
        if self.app.game.pending_gift is not None:
            self._gift_image = self.app.item_image("gift_box", 40)
        self.sprite.set_overlay(self._gift_image)
        self.sprite.show(*self.app.display_sprite())
        if mode == ROAM_TASKBAR and not self._pressed:
            self._align_to_taskbar()
        self.refresh_work_countdown()
        self._place_bubbles()
