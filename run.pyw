"""Windowless launcher — double-click this, or point a Startup shortcut at it.

The .pyw extension makes Windows run it with pythonw.exe, so no console window
appears behind the tray icon.
"""

import sys
import faulthandler
import logging
import threading
import os
import platform
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

def configure_error_log():
    profile = "PokeOfficeBar"
    folder = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / profile
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "error.log"
    if path.exists() and path.stat().st_size > 2_000_000:
        try:
            path.replace(folder / "error.previous.log")
        except OSError:
            pass
    stream = path.open("a", encoding="utf-8", buffering=1)
    sys.stderr = stream
    logging.basicConfig(stream=stream, level=logging.INFO,
                        format="%(asctime)s %(threadName)s %(levelname)s %(message)s")
    faulthandler.enable(file=stream, all_threads=True)
    sys.excepthook = lambda kind, error, trace: logging.critical(
        "Unhandled application error", exc_info=(kind, error, trace))
    threading.excepthook = lambda event: logging.error(
        "Unhandled worker error", exc_info=(event.exc_type, event.exc_value, event.exc_traceback))
    return stream

if __name__ == "__main__":
    try:
        error_log = configure_error_log()
    except OSError:
        pass
    try:
        logging.info("Starting PokeOfficeBar; Windows=%s; Python=%s", platform.win32_ver(), sys.version)
        from pokeofficebar.__main__ import main
        result = main()
        logging.info("PokeOfficeBar exited normally")
        sys.exit(result)
    except Exception as error:
        logging.exception("Application could not start or finish normally")
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,
            "프로그램을 실행하지 못했습니다. 오류 로그를 확인해 주세요.\n"
            "%LOCALAPPDATA%\\PokeOfficeBar\\error.log\n\n" + str(error)[:200],
            "PokeOfficeBar", 0x10)
        sys.exit(1)
