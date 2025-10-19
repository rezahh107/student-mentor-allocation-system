
from __future__ import annotations
import os, tempfile
from pathlib import Path
from typing import Optional

def _detect_crlf(text: str) -> bool:
    # If any CRLFs exist and no lone LFs, treat as CRLF
    return "\r\n" in text and "\n" in text

def atomic_write(path: Path, data: str, *, clock=None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Preserve newline style of existing file if present
    newline = None
    if path.exists():
        with path.open("rb") as f:
            sample = f.read(4096)
        if b"\r\n" in sample and b"\n" in sample:
            newline = "\r\n"
    tmp = Path(str(path) + ".part")
    # Write text exactly; if newline is set, normalize all \n to CRLF
    out = data
    if newline == "\r\n":
        out = data.replace("\r\n", "\n").replace("\n", "\r\n")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        fh.write(out)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
