"""Register this app to run when the current Windows user signs in."""

import sys
import winreg
from pathlib import Path
from subprocess import list2cmdline

STARTUP_ARGUMENT = "--startup"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "PokeOfficeBar"


def _command() -> str:
    executable = Path(sys.executable)
    if getattr(sys, "frozen", False):
        args = [str(executable), STARTUP_ARGUMENT]
    else:
        windowless = executable.with_name("pythonw.exe")
        python = windowless if windowless.is_file() else executable
        launcher = Path(__file__).resolve().parent.parent / "run.pyw"
        args = [str(python), str(launcher), STARTUP_ARGUMENT]
    command = list2cmdline(args)
    if len(command.encode("utf-16-le")) // 2 > 260:
        raise OSError("Windows startup command exceeds the 260-character Run limit")
    return command


def set_startup(enabled: bool) -> None:
    if not enabled:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass
        return

    desired = (_command(), winreg.REG_SZ)
    access = winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, access) as key:
        try:
            existing = winreg.QueryValueEx(key, VALUE_NAME)
        except FileNotFoundError:
            existing = None
        if existing != desired:
            winreg.SetValueEx(key, VALUE_NAME, 0, desired[1], desired[0])
