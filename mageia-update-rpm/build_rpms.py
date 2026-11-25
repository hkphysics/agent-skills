#!/usr/bin/env python3
"""Build Python packages in batches.

Usage:
    build_rpms.py [N] [--all | --packages PKG [PKG ...]] [--background]

For each package: mgarepo co -> bump Version/Release -> spectool -g ->
move sources into SOURCES/ -> instbr dry-run -> bm build.

Modes:
    N            build the first N packages from the CSV (default 20)
    --all        build every package found in buildroot directories
    --packages   build only the named packages

After the run stops, errors can be analysed and fixed.  Use --background
to run the next batch of N asynchronously.
"""
import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

MAGEIA_ROOT = Path(os.getenv("MAGEIA_ROOT", "./mgarepo"))
INSTBR = os.getenv("MAGEIA_INSTBR",
                   "/home/joe/.pi/agent/skills/mageia-update-rpm/instbr.py")
DEFAULT_CSV = os.getenv("MAGEIA_CSV", "/tmp/python_no_maintainer.csv")
DEFAULT_LOG = os.getenv("MAGEIA_LOG", "/tmp/pipe_results.tsv")
SCRIPT = str(Path(__file__).resolve())


def run(cmd, cwd=None, timeout=900):
    """Run a shell command, return (returncode, stdout+stderr)."""
    try:
        r = subprocess.run(
            cmd, shell=True, cwd=str(cwd) if cwd else None,
            capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"


def count_rpms(pkg: str) -> int:
    d = MAGEIA_ROOT / pkg / "RPMS"
    if not d.is_dir():
        return 0
    return sum(1 for _, _, files in os.walk(d)
               for fn in files
               if fn.endswith(".rpm") and "debug" not in fn.lower())


def read_spec_version(spec_path: Path) -> str:
    m = re.search(r"^Version:\s*(.+)", spec_path.read_text(), flags=re.M)
    return m.group(1).strip() if m else ""


def bump_spec(pkg: str, avail: str, pdir: Path) -> None:
    spec = pdir / "SPECS" / f"{pkg}.spec"
    c = spec.read_text()
    c = re.sub(r"^Version:.*$", f"Version:        {avail}", c, count=1, flags=re.M)
    c = re.sub(r"^Release:.*$", "Release:        %mkrel 1", c, count=1, flags=re.M)
    spec.write_text(c)


def move_to_sources(pdir: Path, pkg: str) -> None:
    sources = pdir / "SOURCES"
    sources.mkdir(exist_ok=True)
    skip = {"SOURCES", "SPECS", "RPMS", "SRPMS", "BUILD", "BUILDROOT"}
    for entry in pdir.iterdir():
        if entry.name.startswith(".") or entry.name == "__pycache__" or entry.name in skip:
            continue
        if not entry.is_file():
            continue
        dst = sources / entry.name
        if dst.exists():
            shutil.move(str(entry), str(dst))
        else:
            shutil.copy2(str(entry), str(dst))


def dep_status(out: str) -> str:
    if "Unresolved: 0" in out or "No install performed" in out:
        return "deps_ok"
    if "Unresolved:" in out:
        return "deps_missing"
    if "already satisfied" in out.lower():
        return "deps_ok"
    return "dep_unknown"


def has_log_file(pdir: Path) -> bool:
    """Check if there's a log file in SPECS/ directory."""
    specs = pdir / "SPECS"
    if not specs.is_dir():
        return False
    return any(f.name.startswith("log.") for f in specs.iterdir() if f.is_file())


def process_pkg(pkg: str, avail: str, skip_with_log: bool = False):
    """Process one package. Returns (status, dep_status, rpm_count)."""
    pdir = MAGEIA_ROOT / pkg
    if not pdir.is_dir():
        rc, out = run(f"mgarepo co {pkg}", cwd=MAGEIA_ROOT, timeout=600)
        if not pdir.is_dir():
            return "CHECKOUT_FAIL", "", 0

    spec = pdir / "SPECS" / f"{pkg}.spec"
    if not spec.exists():
        return "NO_SPEC", "", 0

    if skip_with_log and has_log_file(pdir):
        return "SKIP_WITH_LOG", "", 0

    bump_spec(pkg, avail, pdir)
    run(f"spectool -g SPECS/{pkg}.spec", cwd=pdir, timeout=600)
    move_to_sources(pdir, pkg)

    _, out = run(f"python3 {INSTBR} {pkg} --root {MAGEIA_ROOT} --dry-run",
                  cwd=pdir, timeout=300)
    dep = dep_status(out)

    _, out2 = run(f"bm SPECS/{pkg}.spec", cwd=pdir, timeout=1200)
    Path(f"/tmp/build_log_{pkg}.txt").write_text(out2)

    rpms = count_rpms(pkg)
    status = "BUILT" if rpms > 0 else (
        "DEP_FAIL" if ("依賴關係建置失敗" in out2
                       or "Failed build dependencies" in out2
                       or "unsatisfied" in out2.lower())
        else "BUILD_FAIL")
    return status, dep, rpms


def load_csv(path):
    rows = []
    if path:
        with open(path) as f:
            rows = [(row["source_package"], row["available_version"])
                    for row in csv.DictReader(f)]
    by_name = {r[0]: r for r in rows}
    return rows, by_name


def discover_all():
    selected = []
    for entry in sorted(MAGEIA_ROOT.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        spec_path = entry / "SPECS" / f"{entry.name}.spec"
        if spec_path.exists():
            selected.append((entry.name, read_spec_version(spec_path)))
    return selected


def main():
    global MAGEIA_ROOT
    parser = argparse.ArgumentParser(
        prog="build_rpms.py",
        description=("Build Python packages in batches.\n\n"
                     "For each package: mgarepo co -> bump Version/Release -> spectool -g ->\n"
                     "move sources into SOURCES/ -> instbr dry-run -> bm build."),
        epilog=(
            "Examples:\n"
            "  build_rpms.py              # build 20 packages (default batch)\n"
            "  build_rpms.py 50           # build 50 packages\n"
            "  build_rpms.py --all        # build every package found in buildroot directories\n"
            "  build_rpms.py --packages foo bar baz  # build named packages\n"
            "  build_rpms.py 20 --background  # build 20, then chain next 20 in background"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("n", nargs="?", type=int, metavar="N",
                      help="build the first N packages from the CSV (default 20)")
    mode.add_argument("--all", action="store_true",
                      help="build every package found in buildroot directories")
    mode.add_argument("--packages", "-p", nargs="+", metavar="PKG",
                      help="build only these named packages")
    parser.add_argument("--background", action="store_true",
                        help="after finishing, launch the next N packages in the background (N mode only)")
    parser.add_argument("--skip", type=int, default=0,
                        help="skip the first N packages in the CSV")
    parser.add_argument("--skip-with-log", action="store_true",
                        help="skip packages that have a log file in SPECS/"),
    parser.add_argument("--csv", help="CSV of packages (optional)")
    parser.add_argument("--log", default=DEFAULT_LOG,
                        help="result log file (default: %(default)s)")
    parser.add_argument("--root", default=str(MAGEIA_ROOT),
                        help="mgarepo root directory (default: %(default)s)")
    args = parser.parse_args()

    MAGEIA_ROOT = Path(args.root)

    rows, by_name = load_csv(args.csv)

    if args.all:
        selected = discover_all()
    elif args.packages:
        missing = [p for p in args.packages if p not in by_name]
        if missing:
            print(f"Packages not found in CSV: {', '.join(missing)}", file=sys.stderr)
        selected = [by_name[p] for p in args.packages if p in by_name]
        if not selected:
            print("No valid packages to build.", file=sys.stderr)
            sys.exit(1)
    else:
        if not args.csv:
            parser.error("either --all, --packages, or --csv is required")
        n = args.n if args.n is not None else 20
        selected = rows[:n]

    if args.skip:
        selected = selected[args.skip:]

    with open(args.log, "a") as logf:
        done = 0
        for pkg, avail in selected:
            status, dep, rpms = process_pkg(pkg, avail, args.skip_with_log)
            print(f"{pkg}\t{status}\t{dep}\trpms={rpms}", flush=True)
            logf.write(f"{pkg}\t{status}\t{dep}\trpms={rpms}\n")
            logf.flush()
            done += 1
    print(f"\nBatch complete: {done} packages processed", flush=True)

    if args.background and args.n is not None and not args.all and not args.packages:
        start = args.n
        end = min(start + args.n, len(rows))
        if start < end:
            next_pkgs = [r[0] for r in rows[start:end]]
            Path("/tmp/next_batch_pkgs.txt").write_text("\n".join(next_pkgs) + "\n")
            subprocess.Popen(
                [sys.executable, SCRIPT, str(args.n), "--background"],
                cwd=str(MAGEIA_ROOT),
                stdout=open("/tmp/pipeline_next.log", "ab"),
                stderr=subprocess.STDOUT,
            )
            print(f"Background next batch started: {len(next_pkgs)} packages", flush=True)


if __name__ == "__main__":
    main()
