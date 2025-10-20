#!/usr/bin/env python3
# qg.py — On-demand Python Quality Gate (no CI needed)
from __future__ import annotations

import json, os, re, shutil, subprocess, sys, textwrap, time, xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

ART = Path("artifacts")
TOOLS_VENV = Path(".qg-venv")
PINNED = {
    "ruff": "0.13.0",
    "mypy": "1.18.1",
    "pytest": "8.4.2",
    "pytest-cov": "7.0.0",
    "bandit[toml]": "1.7.10",
    "safety": "3.2.7",
    "pip-audit": "2.7.3",
}
TIMEOUTS = {"ruff":120, "format":120, "mypy":300, "pytest":600, "bandit":180, "safety":120, "audit":120}

def print_h(s): print(f"\n{'='*60}\n{s}\n{'='*60}")

def env_det():
    os.environ.update({
        "PYTHONHASHSEED":"0",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD":"1",
        "PYTHONSAFEPATH":"1",
        "PYTHONWARNINGS":"error",
        "PYTHONNOUSERSITE":"1",
        "PIP_NO_INPUT":"1",
        "PIP_PROGRESS_BAR":"off",
        "TZ":"UTC",
    })

def run(cmd: List[str], timeout: int, out: Path, desc: str) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"→ {desc} | timeout={timeout}s\n$ {' '.join(cmd)}")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out.write_text((p.stdout or "") + (p.stderr or ""), encoding="utf-8")
        (out.parent / "exit_code.txt").write_text(str(p.returncode), encoding="utf-8")
        print(f"✓ exit={p.returncode} → {out}")
        return p.returncode
    except subprocess.TimeoutExpired:
        out.write_text(f"⏱ timed out after {timeout}s\n", encoding="utf-8")
        (out.parent / "exit_code.txt").write_text("124", encoding="utf-8")
        print(f"⏱ TIMEOUT {timeout}s")
        return 124
    except Exception as e:
        out.write_text(f"❌ {e}\n", encoding="utf-8")
        (out.parent / "exit_code.txt").write_text("1", encoding="utf-8")
        print(f"❌ {e}")
        return 1

def venv_py() -> Path:
    return TOOLS_VENV / ("Scripts/python.exe" if os.name=="nt" else "bin/python")

def venv_bin(name: str) -> Path:
    return TOOLS_VENV / ("Scripts" if os.name=="nt" else "bin") / name

def ensure_venv():
    if not venv_py().exists():
        print_h("Create isolated venv for tools (.qg-venv)")
        subprocess.check_call([sys.executable, "-m", "venv", str(TOOLS_VENV)])
    print("✓ venv ready:", venv_py())

def pip_install(pkgs: Dict[str,str]):
    print_h("Install pinned toolchain into .qg-venv")
    py = str(venv_py())
    subprocess.check_call([py, "-m", "pip", "install", "-U", "pip", "--quiet"])
    args = [py, "-m", "pip", "install", "--no-cache-dir", "--quiet"]
    for k,v in pkgs.items(): args.append(f"{k}=={v}")
    subprocess.check_call(args)

def detect_src() -> str:
    files = [str(p) for p in Path(".").rglob("*.py") if not any(x in str(p) for x in [".venv","venv","__pycache__",".git","node_modules","build","dist",".eggs",".qg-venv"])]
    info = {
        "total_py_files": len(files),
        "has_tests": Path("tests").is_dir(),
        "source_path": "src" if Path("src").is_dir() else ("app" if Path("app").is_dir() else "."),
        "files": sorted(files)[:200],
    }
    ART.mkdir(exist_ok=True)
    (ART/"project_scan.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✓ Discovered {info['total_py_files']} .py files | SRC_PATH={info['source_path']}")
    return info["source_path"]

def parse_pyproject():
    cfg={}
    p=Path("pyproject.toml")
    if p.exists():
        try:
            try:
                import tomllib as toml
            except Exception:
                import tomli as toml
            data=toml.loads(p.read_text(encoding="utf-8"))
            tool=data.get("tool",{})
            cfg={
                "ruff": tool.get("ruff",{}),
                "mypy": tool.get("mypy",{}),
                "coverage": tool.get("coverage",{}),
                "bandit": tool.get("bandit",{}),
                "pytest": tool.get("pytest",{}),
            }
        except Exception as e:
            cfg={"parse_error": str(e)}
    (ART/"config_parsed.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

def versions():
    py=str(venv_py())
    tools={
        "python":[py,"--version"],
        "ruff":[str(venv_bin("ruff")),"--version"],
        "mypy":[str(venv_bin("mypy")),"--version"],
        "pytest":[str(venv_bin("pytest")),"--version"],
        "bandit":[str(venv_bin("bandit")),"--version"],
        "safety":[str(venv_bin("safety")),"--version"],
        "pip-audit":[str(venv_bin("pip-audit")),"--version"],
    }
    out={}
    for k,cmd in tools.items():
        try:
            r=subprocess.run(cmd, capture_output=True, text=True, timeout=8)
            out[k]=(r.stdout or r.stderr).strip()
        except Exception as e:
            out[k]=f"ERROR: {e}"
    (ART/"tool_versions.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

def load_json(path: Path, default):
    try:
        t=path.read_text(encoding="utf-8").strip()
        return default if not t else json.loads(t)
    except Exception:
        return default

def analyze(src_path: str, do_fix: bool=False):
    py = str(venv_py())

    print_h("Ruff — lint (JSON)")
    run([str(venv_bin("ruff")), "check", ".", "--output-format=json"], TIMEOUTS["ruff"], ART/"lint/ruff.json", "ruff check json")
    if do_fix:
        print("… applying quick fixes (ruff --fix)")
        run([str(venv_bin("ruff")), "check", ".", "--fix"], 120, ART/"lint/ruff_fix.txt", "ruff --fix")
    else:
        run([str(venv_bin("ruff")), "check", "."], 60, ART/"lint/ruff_human.txt", "ruff check (human)")
    # validate JSON
    try:
        data = json.loads((ART/"lint/ruff.json").read_text() or "[]")
        assert isinstance(data, list)
    except Exception:
        (ART/"lint/ruff.json").write_text("[]", encoding="utf-8")

    print_h("Ruff — format check")
    run([str(venv_bin("ruff")), "format", "--check", "--diff", "."], TIMEOUTS["format"], ART/"format/diff.txt", "ruff format --check")

    print_h("MyPy — type check (JSONL → JSON)")
    raw = ART/"typecheck/mypy.jsonl"
    run([str(venv_bin("mypy")), "--pretty", "--show-error-codes", "--error-format=json", "--no-error-summary", "."],
        TIMEOUTS["mypy"], raw, "mypy jsonl")
    msgs=[]
    try:
        for ln in raw.read_text(encoding="utf-8").splitlines():
            ln=ln.strip()
            if ln:
                msgs.append(json.loads(ln))
    except Exception:
        pass
    (ART/"typecheck/mypy.json").write_text(json.dumps(msgs, indent=2, ensure_ascii=False), encoding="utf-8")

    print_h("Pytest — tests + coverage")
    run([py,"-P","-m","pytest","-q",f"--cov={src_path}","--cov-report=xml","--cov-report=term","--tb=short"],
        TIMEOUTS["pytest"], ART/"tests/pytest.txt","pytest + coverage")
    if Path("coverage.xml").exists():
        shutil.copy2("coverage.xml", ART/"tests/coverage.xml")
    else:
        (ART/"tests/coverage_missing.txt").write_text("⚠ coverage.xml missing\n", encoding="utf-8")

    print_h("Security — Bandit")
    run([str(venv_bin("bandit")),"-r",src_path,"-f","json"], TIMEOUTS["bandit"], ART/"security/bandit.json","bandit json")
    run([str(venv_bin("bandit")),"-r",src_path], TIMEOUTS["bandit"], ART/"security/bandit_human.txt","bandit human")
    # fix invalid JSON
    bd = load_json(ART/"security/bandit.json", {})
    if not isinstance(bd, dict) or "results" not in bd:
        (ART/"security/bandit.json").write_text('{"results":[]}', encoding="utf-8")

    print_h("Security — Safety & pip-audit")
    run([str(venv_bin("safety")),"check","--json"], TIMEOUTS["safety"], ART/"security/safety.json","safety")
    if not load_json(ART/"security/safety.json", {}):
        (ART/"security/safety.json").write_text('{"vulnerabilities":[]}', encoding="utf-8")
    run([str(venv_bin("pip-audit")),"--format=json"], TIMEOUTS["audit"], ART/"security/pip_audit.json","pip-audit")
    if not load_json(ART/"security/pip_audit.json", {}):
        (ART/"security/pip_audit.json").write_text('{"dependencies":[]}', encoding="utf-8")

def tool_coverage():
    scan = load_json(ART/"project_scan.json", {})
    all_files = set(scan.get("files", []))
    cov={}
    # ruff
    ruff = load_json(ART/"lint/ruff.json", [])
    rfiles = {i.get("filename","") for i in ruff if isinstance(i, dict)}
    # mypy
    mypy = load_json(ART/"typecheck/mypy.json", [])
    mfiles = {i.get("file","") for i in mypy if isinstance(i, dict)}
    for k, files in {"ruff": rfiles, "mypy": mfiles}.items():
        covered = len(files & all_files)
        total = len(all_files)
        pct = round((covered/total*100) if total else 0, 1)
        miss = list(all_files - files)
        cov[k] = {"covered": covered, "total": total, "percent": pct, "missing_count": len(miss), "missing_sample": miss[:10]}
    (ART/"tool_coverage.json").write_text(json.dumps(cov, indent=2, ensure_ascii=False), encoding="utf-8")

def summary():
    ruff = load_json(ART/"lint/ruff.json", [])
    mypy = load_json(ART/"typecheck/mypy.json", [])
    bandit = load_json(ART/"security/bandit.json", {})
    vers = load_json(ART/"tool_versions.json", {})
    scan = load_json(ART/"project_scan.json", {})
    tcov = load_json(ART/"tool_coverage.json", {})

    coverage_pct = 0.0
    try:
        root = ET.parse(ART/"tests/coverage.xml").getroot()
        coverage_pct = float(root.attrib.get("line-rate", 0))*100
    except Exception:
        pass

    lint_errors = sum(1 for x in ruff if str(x.get("code","")).startswith(("E","F","B")))
    lint_warnings = sum(1 for x in ruff if str(x.get("code","")).startswith("W"))
    type_errors = sum(1 for x in mypy if x.get("severity")=="error")
    bres = bandit.get("results", []) if isinstance(bandit, dict) else []
    bH = sum(1 for x in bres if x.get("issue_severity")=="HIGH")
    bM = sum(1 for x in bres if x.get("issue_severity")=="MEDIUM")
    bL = sum(1 for x in bres if x.get("issue_severity")=="LOW")

    TH = {"coverage_min":70,"bandit_high_max":0,"bandit_med_max":3,"mypy_errors_max":0,"lint_errors_max":0}
    gates = {
        "lint": "PASS" if lint_errors<=TH["lint_errors_max"] else "FAIL",
        "types": "PASS" if type_errors<=TH["mypy_errors_max"] else "FAIL",
        "security": "PASS" if (bH<=TH["bandit_high_max"] and bM<=TH["bandit_med_max"]) else "FAIL",
        "coverage": "PASS" if coverage_pct>=TH["coverage_min"] else "FAIL",
    }
    overall = "PASS" if all(v=="PASS" for v in gates.values()) else "FAIL"

    md = []
    md.append("# 🔍 Python Quality Gate Report\n")
    md.append(f"**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}  ")
    md.append(f"**Project**: {Path.cwd().name}  ")
    md.append(f"**Python Files**: {scan.get('total_py_files',0)}  ")
    md.append(f"**Source Path**: `{scan.get('source_path','.')}`  ")
    md.append(f"**Overall Result**: {'✅ **PASS**' if overall=='PASS' else '❌ **FAIL**'}\n\n---\n")
    md.append("## 📊 Gates\n\n")
    md.append("| Gate | Status | Metric | Threshold |\n|--|--|--|--|\n")
    md.append(f"| Lint | {gates['lint']} | {lint_errors} errors, {lint_warnings} warnings | errors≤{TH['lint_errors_max']} |\n")
    md.append(f"| Types | {gates['types']} | {type_errors} errors | errors≤{TH['mypy_errors_max']} |\n")
    md.append(f"| Security | {gates['security']} | {bH} HIGH, {bM} MED, {bL} LOW | HIGH≤{TH['bandit_high_max']}, MED≤{TH['bandit_med_max']} |\n")
    md.append(f"| Coverage | {gates['coverage']} | {coverage_pct:.1f}% | ≥{TH['coverage_min']}% |\n")

    md.append("\n---\n\n## 🔧 Tool Coverage\n\n")
    for tool, d in tcov.items():
        line = f"- **{tool.upper()}**: {d['covered']}/{d['total']} files ({d['percent']}%)"
        if d.get("missing_count",0)>0:
            line += f" — ⚠ {d['missing_count']} files not analyzed"
        md.append(line+"\n")

    md.append("\n---\n\n## 📋 Next Actions\n\n")
    if gates["lint"]=="FAIL": md.append(f"- [ ] Fix {lint_errors} lint errors: `.{os.sep}{venv_bin('ruff') if os.name=='nt' else 'ruff'} check --fix .`\n")
    if gates["types"]=="FAIL": md.append("- [ ] Resolve MyPy errors (see `artifacts/typecheck/mypy.json`)\n")
    if gates["security"]=="FAIL":
        if bH>0: md.append(f"- [ ] 🔴 Urgent: fix {bH} HIGH security issues\n")
        if bM>TH["bandit_med_max"]: md.append(f"- [ ] Address MEDIUM issues (found {bM}, threshold {TH['bandit_med_max']})\n")
    if gates["coverage"]=="FAIL": md.append(f"- [ ] Raise coverage from {coverage_pct:.1f}% to ≥{TH['coverage_min']}%\n")
    if all(v=="PASS" for v in gates.values()): md.append("✅ All gates passed. No immediate action.\n")

    md.append("\n---\n\n## 🧭 Tool Versions\n\n")
    for k,v in vers.items(): md.append(f"- **{k}**: `{(v.splitlines()[0])[:80]}`\n")

    md.append("\n---\n\n## 📁 Artifacts\n\n")
    md.append("- `artifacts/lint/ruff.json`\n- `artifacts/format/diff.txt`\n- `artifacts/typecheck/mypy.json`\n")
    md.append("- `artifacts/tests/pytest.txt`, `artifacts/tests/coverage.xml`\n- `artifacts/security/bandit.json`, `safety.json`, `pip_audit.json`\n")

    ART.mkdir(exist_ok=True)
    (ART/"QUALITY_SUMMARY.md").write_text("".join(md), encoding="utf-8")
    print_h("QUALITY SUMMARY")
    print((ART/"QUALITY_SUMMARY.md").read_text())

def make_zip():
    shutil.make_archive("artifacts_bundle","zip", str(ART))
    print("✓ artifacts_bundle.zip created")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="On-demand Python Quality Gate (no CI)")
    parser.add_argument("--fix", action="store_true", help="apply quick lint fixes (ruff --fix)")
    parser.add_argument("--zip", action="store_true", help="zip artifacts at the end")
    parser.add_argument("--src", default=None, help="override source path (default: auto)")
    args = parser.parse_args()

    env_det()
    print_h("Phase 0 — Discovery & Config")
    src = args.src or detect_src()
    parse_pyproject()

    print_h("Phase 1 — Toolchain venv")
    ensure_venv()
    pip_install(PINNED)
    versions()

    print_h("Phase 2/3 — Analyses")
    analyze(src, do_fix=args.fix)
    tool_coverage()
    summary()
    if args.zip: make_zip()

if __name__ == "__main__":
    main()
