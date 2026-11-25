"""Native Windows notification-area icon and shared context menu."""

from __future__ import annotations

import threading

import pystray
from pystray._util import win32
from PIL import Image

from .app import ROAM_OFF, ROAM_SCREEN, ROAM_TASKBAR
from .i18n import t

ICON_SIZE = 64
FRAME_MS = 200
WM_REFRESH_MENU = win32.WM_USER + 12
WM_REFRESH_ICON = win32.WM_USER + 13
WM_ANIMATE_ICON = win32.WM_USER + 14
WM_SHOW_ICON = win32.WM_USER + 15


class Tray:
    def __init__(self, app, on_open, on_toggle_pet, on_roam_mode, on_quit,
                 on_toggle_incense=None, on_toggle_work_timer=None) -> None:
        self.app = app
        self.on_open = on_open
        self._frames: list[Image.Image] = []
        self._index = 0
        self._key = None
        self._stop = threading.Event()
        self._icon_thread = None
        self._menu_open = threading.Event()
        self._menu_active = False
        self._pending_lock = threading.Lock()
        self._pending_frames = None
        self._pending_title = None
        self._refresh_posted = False
        self._animation_posted = False
        self._animation_thread = None

        # Labels are callables so switching language relabels the menu without
        # rebuilding the icon.
        def roam_item(mode):
            return pystray.MenuItem(
                lambda _: t(f"tray.roam.{mode}"), lambda *_: on_roam_mode(mode),
                checked=lambda _: mode == (app.config.pet_roam_mode
                                           if app.config.floating_pet else ROAM_OFF),
                radio=True,
            )

        def incense_status():
            return app.game.incense_status()

        menu = pystray.Menu(
            pystray.MenuItem(lambda _: t("tray.open"), lambda *_: on_open(),
                             default=True),
            pystray.MenuItem(lambda _: t("tray.refresh"),
                             lambda *_: app.request_refresh()),
            pystray.MenuItem(lambda _: t("tray.pet"), lambda *_: on_toggle_pet(),
                             checked=lambda _: app.config.floating_pet),
            pystray.MenuItem(lambda _: t("set.work_timer"), lambda *_: on_toggle_work_timer(),
                             checked=lambda _: app.config.work_timer_enabled,
                             visible=on_toggle_work_timer is not None),
            pystray.MenuItem(
                lambda _: t("tray.roam"),
                pystray.Menu(roam_item(ROAM_OFF), roam_item(ROAM_SCREEN), roam_item(ROAM_TASKBAR)),
            ),
            pystray.MenuItem(
                lambda _: t("incense.off" if incense_status()[0] else "incense.on"),
                lambda *_: on_toggle_incense(),
                enabled=lambda _: incense_status()[1] > 0,
                visible=on_toggle_incense is not None,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda _: t("tray.quit"), lambda *_: on_quit()),
        )
        self.icon = pystray.Icon(
            "pokeofficebar", self._placeholder(), t("app.title"), menu
        )
        self.icon._message_handlers[win32.WM_NOTIFY] = self._on_notify
        self.icon._message_handlers[WM_REFRESH_MENU] = self._refresh_menu
        self.icon._message_handlers[WM_REFRESH_ICON] = self._apply_pending
        self.icon._message_handlers[WM_ANIMATE_ICON] = self._advance_frame
        self.icon._message_handlers[WM_SHOW_ICON] = self._show_icon

    @property
    def menu_open(self) -> bool:
        return self._menu_open.is_set()

    def show_menu(self) -> None:
        """Show the actual tray popup on its owner thread at the pointer."""
        if self._stop.is_set() or not self.icon._hwnd or self.menu_open:
            return
        self._menu_open.set()
        try:
            if not win32.PostMessage(self.icon._hwnd, win32.WM_NOTIFY, 0, win32.WM_RBUTTONUP):
                self._menu_open.clear()
        except OSError:
            self._menu_open.clear()
            raise

    def _on_notify(self, wparam, lparam) -> None:
        if lparam != win32.WM_RBUTTONUP:
            self.icon._on_notify(wparam, lparam)
            return
        if self._menu_active or self._stop.is_set():
            return
        self._menu_active = True
        self._menu_open.set()
        try:
            self.icon.update_menu()
            # TrackPopupMenuEx returns before pystray invokes the chosen action;
            # the action only places plain data in the Tk thread's mailbox.
            self.icon._on_notify(wparam, lparam)
        finally:
            self._menu_active = False
            self._menu_open.clear()
            self._apply_pending()

    def refresh_menu(self) -> None:
        if not self._stop.is_set() and self.icon._hwnd:
            win32.PostMessage(self.icon._hwnd, WM_REFRESH_MENU, 0, 0)

    def _refresh_menu(self, wparam=0, lparam=0) -> None:
        # A posted refresh can arrive within TrackPopupMenuEx's native loop.
        # Rebuild on the next opening instead of deleting a posted HMENU.
        if not self.menu_open and not self._stop.is_set():
            self.icon.update_menu()

    @staticmethod
    def _placeholder() -> Image.Image:
        return Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))

    def start(self) -> None:
        self._icon_thread = threading.Thread(target=self.icon.run, args=(self._setup,),
                                             name="poke-tray", daemon=True)
        self._icon_thread.start()
        self._animation_thread = threading.Thread(target=self._animate, name="poke-tray-anim", daemon=True)
        self._animation_thread.start()

    def _setup(self, icon) -> None:
        if self._stop.is_set():
            icon.stop()
        else:
            win32.PostMessage(icon._hwnd, WM_SHOW_ICON, 0, 0)

    def _show_icon(self, wparam=0, lparam=0) -> None:
        if not self._stop.is_set():
            self._apply_pending()
            self.icon.visible = True

    def stop(self) -> None:
        self._stop.set()
        if self._animation_thread is not None and self._animation_thread is not threading.current_thread():
            self._animation_thread.join(timeout=1)
        try:
            if self.icon._menu_hwnd:
                win32.PostMessage(self.icon._menu_hwnd, 0x001F, 0, 0)  # WM_CANCELMODE
            self.icon.stop()
        except Exception:
            pass
        if self._icon_thread is not None and self._icon_thread is not threading.current_thread():
            self._icon_thread.join(timeout=2)

    def refresh(self) -> None:
        """Pull the current companion and wallet into the icon and tooltip."""
        app = self.app
        if app.error:
            self._queue_icon(title=t("tray.error", err=app.error))
            return
        if not app.ready:
            return

        species_id, shiny = app.display_sprite()
        new_frames = None
        egg_revision = getattr(app, "egg_art_revision", 0) if species_id is None else 0
        key = (species_id, shiny, egg_revision)
        if key != self._key:
            frames = (
                app.frames(species_id, shiny, ICON_SIZE)
                if species_id is not None
                else app.egg_frames(ICON_SIZE, shiny=shiny)
            )
            self._key = key if frames else None
            new_frames = tuple(frames or [self._placeholder()])

        name = t("egg.shiny" if shiny else "egg.name")
        if species_id is not None:
            species = app.dex.species.get(species_id)
            if species:
                name = species.name(app.config.language) + (" ✨" if shiny else "")
        summary = t("office.balance", balance=app.game.currency(app.game_total))
        self._queue_icon(frames=new_frames, title=f"{name}\n{summary}")

    def _queue_icon(self, frames=None, title=None) -> None:
        if self._stop.is_set():
            return
        with self._pending_lock:
            if frames is not None:
                self._pending_frames = frames
            if title is not None:
                self._pending_title = title[:127]
            if self._icon_thread is not None:
                if self.icon._hwnd and not self._refresh_posted:
                    self._refresh_posted = bool(win32.PostMessage(self.icon._hwnd, WM_REFRESH_ICON, 0, 0))
                return
        # Before start there are no native resources or competing owner thread.
        self._apply_pending()

    def _apply_pending(self, wparam=0, lparam=0) -> None:
        with self._pending_lock:
            self._refresh_posted = False
            if self._stop.is_set() or self.menu_open:
                return
            frames, title = self._pending_frames, self._pending_title
            self._pending_frames = self._pending_title = None
        if frames is not None:
            self._frames = frames
            self._index = 0
            self.icon.icon = frames[0]
        if title is not None:
            self.icon.title = title

    def _advance_frame(self, wparam=0, lparam=0) -> None:
        with self._pending_lock:
            self._animation_posted = False
        if self._stop.is_set() or self.menu_open or not self.app.config.animate_tray or len(self._frames) < 2:
            return
        self._index = (self._index + 1) % len(self._frames)
        self.icon.icon = self._frames[self._index]

    def _animate(self) -> None:
        while not self._stop.wait(FRAME_MS / 1000):
            if self.menu_open or not self.app.config.animate_tray or len(self._frames) < 2:
                continue
            with self._pending_lock:
                if self.icon._hwnd and not self._animation_posted:
                    self._animation_posted = bool(win32.PostMessage(self.icon._hwnd, WM_ANIMATE_ICON, 0, 0))
