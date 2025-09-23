from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from PyQt5.QtGui import QFont, QFontDatabase
from PyQt5.QtWidgets import QApplication


def fonts_dir() -> Path:
    """Return the expected fonts directory (assets/fonts)."""
    # project_root/ -> locate by walking up from this file
    here = Path(__file__).resolve()
    root = here.parents[3] if len(here.parents) >= 3 else here.parent
    return (root / "assets" / "fonts").resolve()


def install_persian_fonts(app: QApplication) -> dict:
    """Install Persian fonts into Qt and configure defaults.

    Attempts to load fonts from assets/fonts (Vazir, B-Nazanin, Tahoma).
    Sets application default font to Vazir (or fallback). Returns info dict.
    """
    fdir = fonts_dir()
    info = {"fonts_dir": str(fdir), "loaded": [], "default": None}

    # Gracefully handle missing directory
    if not fdir.exists():
        logging.warning("Fonts directory not found: %s", fdir)
        _apply_default_font(app, ["Vazir", "IRANSans", "Tahoma", "Segoe UI"])
        info["default"] = app.font().family()
        return info

    font_files = [
        "Vazir.ttf",
        "Vazir-Regular.ttf",
        "B-Nazanin.ttf",
        "Tahoma.ttf",
    ]

    loaded_families: List[str] = []
    for fname in font_files:
        fpath = fdir / fname
        if fpath.exists():
            fid = QFontDatabase.addApplicationFont(str(fpath))
            if fid != -1:
                families = QFontDatabase.applicationFontFamilies(fid)
                loaded_families.extend(families)
                logging.info("Loaded font: %s (%s)", fname, ", ".join(families))
            else:
                logging.warning("Failed to load font: %s", fpath)

    # Choose default
    preferred = ["Vazir", "IRANSans", "B Nazanin", "B-Nazanin", "Tahoma", "Segoe UI"]
    _apply_default_font(app, preferred)
    info["default"] = app.font().family()
    info["loaded"] = loaded_families
    return info


def _apply_default_font(app: QApplication, preferred_families: List[str]) -> None:
    for fam in preferred_families:
        f = QFont(fam, 10)
        # Qt will fall back if family not available; set the first to hint
        if f.family():
            app.setFont(f)
            return
    app.setFont(QFont())  # system default


def configure_matplotlib(font_family: Optional[str] = None) -> None:
    """Configure matplotlib rcParams for Persian fonts if installed."""
    try:
        import matplotlib as mpl
        families = [font_family] if font_family else []
        families.extend(["Vazir", "B Nazanin", "B-Nazanin", "Tahoma", "Arial Unicode MS"])  # fallbacks
        mpl.rcParams["font.family"] = families
        mpl.rcParams["axes.unicode_minus"] = False
    except Exception:  # matplotlib may be optional
        pass

