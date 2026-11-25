"""Replace a portable EXE from a separate copy of its launcher."""

from hashlib import file_digest
import logging
import os
from pathlib import Path
from shutil import copyfile
from subprocess import Popen
import sys
from time import monotonic, sleep

from .startup import STARTUP_ARGUMENT
from .updates import StagedUpdate, discard_stage, stage_prefix


INSTALL_ARGUMENT = "--apply-update"
RESTART_ARGUMENT = "--update-restarted"
FAILED_ARGUMENT = "--update-failed"


def is_stage(directory: Path, executable: Path) -> bool:
    return (directory.parent == executable.parent
            and directory.name.startswith(stage_prefix(executable)))


def _launch(executable: Path, *arguments: str) -> Popen:
    # A one-file child that outlives this process needs its own unpacked runtime.
    return Popen([str(executable), *arguments],
                 env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"})


def launch_installer(update: StagedUpdate, *, from_startup: bool) -> None:
    executable = Path(sys.executable).resolve()
    helper = update.directory / "installer.exe"
    copyfile(executable, helper)
    startup = [STARTUP_ARGUMENT] if from_startup else []
    _launch(helper, INSTALL_ARGUMENT, str(executable), update.digest, *startup)


def _replace(source: Path, executable: Path) -> None:
    # The original PyInstaller parent can still be exiting after Python stops.
    # A running image may allow a rename on Windows, so test for write access first.
    deadline = monotonic() + 20
    while True:
        try:
            with executable.open("r+b"):
                pass
            source.replace(executable)
            return
        except PermissionError:
            if monotonic() >= deadline:
                raise
            sleep(.2)


def install_update(executable: Path, digest: str, *, from_startup: bool) -> int:
    helper = Path(sys.executable).resolve()
    directory = helper.parent
    if (not getattr(sys, "frozen", False) or helper.name != "installer.exe"
            or not is_stage(directory, executable)):
        return 1

    candidate = directory / "candidate.exe"
    previous = directory / "previous.exe"
    ready = directory / "ready"
    arguments = [RESTART_ARGUMENT, str(directory)]
    if from_startup:
        arguments.append(STARTUP_ARGUMENT)
    replaced = False
    try:
        with candidate.open("rb") as stream:
            if file_digest(stream, "sha256").hexdigest() != digest:
                raise ValueError("Staged release failed SHA-256 verification")
        copyfile(executable, previous)
        _replace(candidate, executable)
        replaced = True
        child = _launch(executable, *arguments)
        deadline = monotonic() + 45
        while not ready.is_file():
            if child.poll() is not None:
                if ready.is_file():
                    break
                raise OSError(f"Updated application exited during startup ({child.returncode})")
            if monotonic() >= deadline:
                # A slow or blocked child still owns this path. Keep the backup.
                logging.warning("Update startup pending; previous build kept at %s", previous)
                return 1
            sleep(.2)
        logging.info("Updated executable launched successfully: %s", executable)
        return 0
    except (OSError, ValueError):
        logging.exception("Could not install the update")
        try:
            if replaced:
                _replace(previous, executable)
            _launch(executable, *arguments, FAILED_ARGUMENT)
        except OSError:
            logging.exception("Could not restart the previous version; backup path: %s", previous)
        return 1
    finally:
        try:
            (directory / "finished").touch()
        except OSError:
            logging.exception("Could not mark the installer as finished")


def finish_restart(directory: Path) -> None:
    try:
        (directory / "ready").touch()
    except OSError:
        logging.exception("Could not acknowledge the application restart")
        return
    # The helper is still running when the restarted application reports ready.
    deadline = monotonic() + 20
    while True:
        try:
            if (directory / "finished").is_file():
                discard_stage(directory)
                return
        except PermissionError:
            pass
        except OSError:
            logging.exception("Could not clean up the update directory")
            return
        if monotonic() >= deadline:
            logging.info("Update files are still in use: %s", directory)
            return
        sleep(.2)
