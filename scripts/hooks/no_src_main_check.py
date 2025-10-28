import sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKSLASH = chr(92)
TARGETS = ("src" + ".main:app", "src" + BACKSLASH + "main.py")

bad = []
for p in ROOT.rglob("*"):
    if p.is_file() and p.suffix.lower() in {".py",".md",".bat",".ps1",".txt",".toml",".yml",".yaml"}:
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore").lower()
        except Exception:
            continue
        if any(target in txt for target in TARGETS):
            bad.append(str(p.relative_to(ROOT)))

if bad:
    message = ("Found forbidden references to src" + ".main:app or src" + BACKSLASH + "main.py variants:\n")
    sys.stderr.write(message)
    for b in bad:
        sys.stderr.write(f" - {b}\n")
    sys.exit(1)
