from __future__ import annotations

import os
import sys
from pathlib import Path
from shutil import which

from pytesseract import pytesseract


def configure_tesseract() -> Path | None:
    tesseract_dir = find_bundled_tesseract_dir()
    if tesseract_dir:
        executable = tesseract_dir / "tesseract.exe"
        tessdata = tesseract_dir / "tessdata"
        pytesseract.tesseract_cmd = str(executable)
        os.environ["PATH"] = f"{tesseract_dir}{os.pathsep}{os.environ.get('PATH', '')}"
        if tessdata.exists():
            os.environ["TESSDATA_PREFIX"] = str(tessdata)
        return executable

    executable = which("tesseract")
    if executable:
        pytesseract.tesseract_cmd = executable
        return Path(executable)

    return None


def find_bundled_tesseract_dir() -> Path | None:
    candidates = [
        _bundle_root() / "tesseract",
        _project_root() / "vendor" / "tesseract",
    ]
    for candidate in candidates:
        if (candidate / "tesseract.exe").exists():
            return candidate
    return None


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return _project_root()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]
