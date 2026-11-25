"""Atomic JSON replacement with a bounded retry for Windows sharing locks."""

import json
import logging
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import sleep


def read_json(path: Path):
    for attempt in range(5):
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except PermissionError:
            if attempt == 4:
                raise
            sleep(.01 * 2**attempt)


def atomic_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", dir=path.parent, prefix=f"{path.stem}.",
                                suffix=".tmp", encoding="utf-8", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, indent=1)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(5):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                sleep(.01 * 2**attempt)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                logging.warning("Temporary save could not be removed: %s", temporary)
