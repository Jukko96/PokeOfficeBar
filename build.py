"""Build PokeOfficeBar.exe with PyInstaller.

    python build.py

Produces `dist/PokeOfficeBar.exe` — a single Windows GUI executable with no
Python install required on the target machine.

"""

from __future__ import annotations

import argparse
import ssl
import subprocess
import sys
from tempfile import NamedTemporaryFile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
ICON = BUILD / "egg.ico"


def make_icon() -> Path:
    """Build a multi-resolution .ico from the egg asset."""
    from pokeofficebar.app import _draw_egg

    # Use the application's own drawing for the Windows executable icon.
    BUILD.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    _draw_egg(256).save(ICON, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"icon      -> {ICON}")
    return ICON


def is_locked(path: Path) -> bool:
    """True if `path` exists but cannot be replaced (the app is running).

    Tested with an exclusive open rather than a rename: Windows lets you rename
    a running executable but not overwrite or delete it, so a rename probe
    reports "free" and the build then fails anyway.
    """
    if not path.exists():
        return False
    try:
        with open(path, "r+b"):
            pass
    except OSError:
        return True
    return False


def make_gui_executable(executable: Path) -> None:
    """Select the Windows GUI subsystem without adding LoadIconMetric imports.

    This is the documented PE /SUBSYSTEM:WINDOWS image setting. Preserve the
    original entry point, imports and complete one-file archive, and recompute
    the PE checksum. A GUI image does not receive a console from Windows.
    """
    import pefile
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(executable))
    image = pefile.PE(str(executable), fast_load=True)
    temporary = None
    try:
        image.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
        if any(entry.dll.lower() == b'comctl32.dll' for entry in image.DIRECTORY_ENTRY_IMPORT):
            raise RuntimeError("Compatibility bootloader must not import COMCTL32")
        image.OPTIONAL_HEADER.Subsystem = 2  # IMAGE_SUBSYSTEM_WINDOWS_GUI
        image.OPTIONAL_HEADER.CheckSum = image.generate_checksum()
        with NamedTemporaryFile(dir=executable.parent, prefix=executable.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
        image.write(str(temporary))
        rebuilt = CArchiveReader(str(temporary))
        if rebuilt.toc != archive.toc or rebuilt.options != archive.options:
            raise RuntimeError("GUI conversion changed the embedded application archive")
        if temporary.stat().st_size != executable.stat().st_size:
            raise RuntimeError("GUI conversion changed the executable size")
        image.close()
        temporary.replace(executable)
    finally:
        image.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pokemon-data", type=Path, help="Optional local data pack for an offline build")
    args = parser.parse_args()
    icon = make_icon()
    # .pyw forces PyInstaller's windowed bootloader, which statically imports
    # COMCTL32 ordinal 380 (LoadIconMetric). Some Windows 10 systems fail to
    # activate common-controls v6 despite a valid embedded manifest. The
    # official console bootloader avoids that import. Set the final PE image to
    # the Windows GUI subsystem after bundling, so no console is allocated.
    launcher = BUILD / "run.py"
    launcher.write_text((ROOT / "run.pyw").read_text(encoding="utf-8"), encoding="utf-8")

    # Rebuilding while the app runs fails on Windows because the exe is locked.
    # Rather than demand it be closed (or kill it), write beside it.
    name = "PokeOfficeBar"
    target = ROOT / "dist" / "PokeOfficeBar.exe"
    if is_locked(target):
        name = "PokeOfficeBar-new"
        print("note      -> PokeOfficeBar.exe is running and locked;\n"
              "             building as PokeOfficeBar-new.exe instead.")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--console",
        "--paths", str(ROOT),
        "--name", name,
        "--icon", str(icon),
        "--add-data", f"{ROOT / 'LICENSE'}:.",
        "--add-data", f"{ROOT / 'pokeofficebar' / 'assets' / 'expeditions'}:assets/expeditions",
        # pystray and Pillow pick their backends at runtime, so PyInstaller's
        # static analysis misses them.
        "--hidden-import", "pystray._win32",
        "--hidden-import", "PIL._tkinter_finder",
        "--collect-submodules", "pystray",
        # Nothing here needs numpy/scipy/matplotlib; excluding them keeps the
        # binary from ballooning if they happen to be installed.
        "--exclude-module", "numpy",
        "--exclude-module", "scipy",
        "--exclude-module", "matplotlib",
        "--exclude-module", "pandas",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
    ]
    if args.pokemon_data is not None:
        cmd.extend(("--add-data", f"{args.pokemon_data.resolve(strict=True)}:pokemon_data"))
    # Some Python runtimes load a local certificate distrust list from ssl.py.
    # Ship that runtime file alongside ssl.py so its HTTPS checks still work.
    runtime_distrust = Path(ssl.__file__).with_name("codex-rejected-cas.pem")
    if runtime_distrust.is_file():
        cmd.extend(("--add-data", f"{runtime_distrust}:."))
    cmd.append(str(launcher))
    print("running   -> PyInstaller")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    exe = ROOT / "dist" / f"{name}.exe"
    if exe.exists():
        make_gui_executable(exe)
        print("launcher  -> Windows GUI; no console allocation or COMCTL32 startup import")
        print(f"\nbuilt     -> {exe}  ({exe.stat().st_size / 1_048_576:.1f} MB)")
        if name != "PokeOfficeBar":
            print("             close the running app, then replace "
                  "PokeOfficeBar.exe with this file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
