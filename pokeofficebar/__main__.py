"""Main-thread desktop windows, tray messages, and the active-time timer."""

from __future__ import annotations

import logging
import sys
import tkinter as tk
from dataclasses import replace
from queue import Empty, SimpleQueue
from time import monotonic

from .app import App, ROAM_OFF
from .desktop import desktop_unlocked
from .game import ExpeditionReturnNotice
from .startup import STARTUP_ARGUMENT
from .tray import Tray
from .ui import FloatingPet, MainWindow
from .visitors import DesktopVisits


def _claim_single_instance():
    """Return a lock handle if we are the only instance, else None.

    Two copies both own the save file and will overwrite each other's progress,
    so a second launch bows out. The lock is a file in the data directory rather
    than a named mutex: the data directory is the thing actually being guarded,
    and a file lock still works when the two processes sit on opposite sides of
    a sandbox boundary (where a Global\\ mutex may be unreachable). Windows
    drops the lock automatically when the process exits, so a crash cannot leave
    the app permanently unlaunchable.
    """
    import msvcrt

    from .app import game_data_dir

    path = game_data_dir() / "instance.lock"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a+b")
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        try:
            handle.close()
        except (OSError, NameError):
            pass
        return None
    return handle


def _run_session(root, *, from_startup: bool) -> None:
    app = App()
    if from_startup:
        if not app.config.start_with_windows:
            return
    else:
        app.sync_windows_startup()
    window = MainWindow(root, app)
    visits = DesktopVisits(root, app, window.refresh_incense)
    state = {"pet": None, "quitting": False}
    mailbox = SimpleQueue()
    jobs = {"poll": None, "office": None}

    def sync_pet() -> None:
        if app.config.floating_pet and state["pet"] is None:
            state["pet"] = FloatingPet(
                root, app, on_click=window.show,
                on_open_settings=lambda: apply([]), on_quit=quit_app,
                on_context_menu=tray.show_menu,
                menu_is_open=lambda: tray.menu_open,
            )
        elif not app.config.floating_pet and state["pet"] is not None:
            state["pet"].destroy()
            state["pet"] = None

    def apply(events: list[str]) -> None:
        if state["quitting"]:
            return
        if tray.menu_open:
            mailbox.put(("update", events))
            return

        # Each surface is refreshed independently. One of them raising must not
        # take the others down with it — a broken floating pet used to stop the
        # tray tooltip updating too, which made the cause hard to spot.
        def surface(name, fn):
            try:
                fn()
            except Exception:
                logging.exception("%s failed to render", name)

        surface("window", lambda: window.render(events))
        surface("visitors", visits.sync)
        surface("pet", sync_pet)
        pet = state["pet"]
        if pet is not None:
            surface("pet", pet.render)
            returns = [event for event in events if isinstance(event, ExpeditionReturnNotice)]
            if returns:
                surface("pet alert", lambda: pet.say("\n".join(returns), expedition_return=True))
            else:
                note = events[-1] if events else None
                if note:
                    surface("pet alert", lambda: pet.say(note))
        surface("tray", tray.refresh)

    def toggle_pet() -> None:
        cfg = replace(app.config)
        cfg.floating_pet = not cfg.floating_pet
        cfg.save(app.config_path)
        app.config = cfg
        window.vars["floating_pet"].set(cfg.floating_pet)
        apply([])
        tray.refresh_menu()

    def toggle_work_timer() -> None:
        cfg = replace(app.config, work_timer_enabled=not app.config.work_timer_enabled)
        cfg.save(app.config_path)
        app.config = cfg
        window.vars["work_timer_enabled"].set(cfg.work_timer_enabled)
        pet = state["pet"]
        if pet is not None:
            pet.refresh_work_countdown()
        tray.refresh_menu()

    def set_roam_mode(mode: str) -> None:
        cfg = replace(app.config)
        cfg.pet_roam_mode = mode
        if mode != ROAM_OFF:
            cfg.floating_pet = True
        cfg.save(app.config_path)
        app.config = cfg
        window.vars["floating_pet"].set(cfg.floating_pet)
        apply([])
        tray.refresh_menu()

    def quit_app() -> None:
        state["quitting"] = True
        root.quit()

    def office_tick() -> None:
        if state["quitting"]:
            return
        try:
            pet = state["pet"]
            if pet is not None:
                pet.refresh_work_countdown()
        except Exception:
            logging.exception("Work countdown could not be displayed")
        try:
            app.tick_office(monotonic(), desktop_unlocked())
            if app.ready and not tray.menu_open:
                window.refresh_office_clock()
        except Exception as exc:
            logging.exception("Office timer failed")
            app.error = str(exc)
            apply([])
        jobs["office"] = root.after(1000, office_tick)

    actions = {"open": window.show, "toggle_pet": toggle_pet, "quit": quit_app,
               "toggle_incense": window.toggle_incense, "toggle_work_timer": toggle_work_timer}

    def poll() -> None:
        # The native popup must close before actions can replace its menu or
        # stop its owner thread. Pet and tray both use this one popup.
        if tray.menu_open:
            jobs["poll"] = root.after(75, poll)
            return
        for _ in range(100):
            try:
                action, value = mailbox.get_nowait()
            except Empty:
                break
            try:
                if action == "update":
                    apply(value)
                elif action == "roam":
                    set_roam_mode(value)
                else:
                    actions[action]()
            except Exception:
                logging.exception("UI action %s failed", action)
            if state["quitting"]:
                return
        jobs["poll"] = root.after(75, poll)

    # These callbacks retain only a plain queue, never a Tk object or bound widget method.
    tray = Tray(app, on_open=lambda: mailbox.put(("open", None)),
                on_toggle_pet=lambda: mailbox.put(("toggle_pet", None)),
                on_roam_mode=lambda mode: mailbox.put(("roam", mode)),
                on_quit=lambda: mailbox.put(("quit", None)),
                on_toggle_incense=lambda: mailbox.put(("toggle_incense", None)),
                on_toggle_work_timer=lambda: mailbox.put(("toggle_work_timer", None)))

    app.subscribe(lambda events: mailbox.put(("update", events)))
    window.bind("<<SettingsChanged>>", lambda _e: apply([]))
    window.bind("<<PinChanged>>", lambda _e: apply([]))
    window.bind("<<IncenseChanged>>", lambda _e: visits.sync())

    tray.start()
    app.start()
    jobs["office"] = root.after(0, office_tick)
    jobs["poll"] = root.after(0, poll)
    if not from_startup:
        window.show()

    try:
        root.mainloop()
    except KeyboardInterrupt:
        quit_app()
    finally:
        state["quitting"] = True
        app.listeners.clear()
        visits.close()
        try:
            app.stop()
        except Exception:
            logging.exception("Session could not be saved during shutdown")
        tray.stop()
        for job in jobs.values():
            if job is not None:
                root.after_cancel(job)
        for widget in root.winfo_children():
            widget.destroy()


def main() -> int:
    lock = _claim_single_instance()
    if lock is None:
        return 0
    root = tk.Tk()
    root.withdraw()

    def callback_error(error_type, error, traceback):
        logging.error("Tk callback failed", exc_info=(error_type, error, traceback))

    root.report_callback_exception = callback_error
    try:
        _run_session(root, from_startup=STARTUP_ARGUMENT in sys.argv[1:])
        return 0
    finally:
        root.destroy()


if __name__ == "__main__":
    sys.exit(main())
