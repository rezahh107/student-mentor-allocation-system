from __future__ import annotations

import json
import os
import pathlib
import sys
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _emit(level: str, event: str, message: str, *, extra: dict[str, Any] | None = None, target=sys.stdout) -> None:
    correlation_id = os.environ.get("SMA_CORRELATION_ID", "pythonpath-guard")
    payload: dict[str, Any] = {
        "level": level,
        "event": event,
        "message": message,
        "correlation_id": correlation_id,
    }
    if extra:
        payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=target)


def _normalized_segments(raw: str) -> list[pathlib.Path]:
    segments: list[pathlib.Path] = []
    for value in (segment.strip() for segment in raw.split(os.pathsep) if segment.strip()):
        expanded = value.replace("$PWD", str(REPO_ROOT)).replace("%CD%", str(REPO_ROOT))
        segments.append(pathlib.Path(expanded).resolve())
    return segments


def _detect_violation(segments: list[pathlib.Path]) -> tuple[bool, dict[str, Any]]:
    repo_root = REPO_ROOT.resolve()
    for idx, segment in enumerate(segments):
        if str(segment).startswith(str(repo_root)):
            return True, {"segment": str(segment), "index": idx, "reason": "repo-root"}
    try:
        cutoff = min(
            idx
            for idx, segment in enumerate(segments)
            if "site-packages" in segment.parts or "dist-packages" in segment.parts
        )
    except ValueError:
        cutoff = len(segments)
    for idx, segment in enumerate(segments[:cutoff]):
        if segment.name == "src" or segment.parts[-1:] == ("src",):
            return True, {"segment": str(segment), "index": idx, "reason": "src-before-site"}
    return False, {"segment_count": len(segments)}


def main() -> int:
    raw = os.environ.get("PYTHONPATH", "")
    if not raw:
        _emit("info", "pythonpath_guard", "متغیر PYTHONPATH تنظیم نشده است؛ بررسی گذشت.")
        return 0
    segments = _normalized_segments(raw)
    violation, details = _detect_violation(segments)
    if violation:
        _emit(
            "error",
            "pythonpath_violation",
            "خطا: مقدار PYTHONPATH نباید مسیر مخزن یا src را قبل از site-packages قرار دهد.",
            extra={"segments": [str(seg) for seg in segments], "details": details},
            target=sys.stderr,
        )
        return 1
    _emit(
        "info",
        "pythonpath_guard",
        "PYTHONPATH بررسی شد؛ ترتیب مسیرها مجاز است.",
        extra={"segments": [str(seg) for seg in segments]},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
