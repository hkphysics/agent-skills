#!/usr/bin/env python3
"""instbr.py — Resolve EVERY buildrequire of Mageia packages, then install them.

Buildrequires come in two kinds:
  * explicit  — the static BuildRequires: lines in the spec. Kept as-is.
  * implicit  — capabilities emitted at build time by
                %generate_buildrequires / %pyproject_buildrequires. These are
                turned into an RPM capability requirement, preferring a
                pkgconfig(...) form (e.g. pkgconfig(udev)) or a
                python3dist(...) form (e.g. python3dist(cloudpickle)).

For each buildrequire the script asks the local rpm database whether something
already provides it. Satisfied deps are skipped; the rest are accumulated and
installed with sudo urpmi once a batch (default 20) has piled up.

Discovery:
    Packages are the subdirectories of the package root (mgarepo/). A directory
    counts as a package when it contains a SPECS/*.spec file.

Usage:
    ./instbr.py                # install buildrequires for every package here
    ./instbr.py pkg1 pkg2      # only those packages (by directory name)
    ./instbr.py --dry-run      # check everything, print the plan, don't install

The package root is mgarepo/. The script looks for mgarepo/ by walking up from
the script's location, then from the current working directory.

Requires root/sudo for the urpmi install step.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from glob import glob

# Capabilities emitted by %generate_buildrequires via pyproject/rpm-macros.
DYN_RE = re.compile(r"(python3dist|python3-|perl|cmake|pkgconfig)\(([^)]+)\)")
# A buildrequire line: "BuildRequires: name, version" (one logical line may
# list several comma-separated capabilities).
BUILDREQUIRE_RE = re.compile(r"^BuildRequires:\s*(.+)$")
# Strip a version constraint, e.g. "pkg >= 1" -> "pkg".
VERSION_RE = re.compile(r"\s*(>=|<=|==|>|<)[^ ]*$")
# A require name: a capability like pkgconfig(name)/perl(name) or a bare
# package name. Used to pull names out of a BuildRequires line so a trailing
# version constraint is dropped, not split into its own junk token.
# The pkgconfig(name) alternation matches the whole parenthesised form even
# when a version sits inside, e.g. "pkgconfig(libicu-devel) >= 68", while the
# bare-name alternation still matches names that end in a symbol (gcc-c++).
NAME_RE = re.compile(
    r"([a-z0-9][a-z0-9.+_-]*\((?:[^)]+?\s*(?:>=|<=|==|>|<)?[\d\w.\s-]+?)\))"
    r"|([a-z0-9][a-z0-9.+_-]*[\d\w.+-]*)"
)
# A bare numeric version fragment such as the "68" in "name >= 68", captured
# by NAME_RE but never a real requirement.
VERSION_ONLY_RE = re.compile(r"^\d+(\.\d+)*$")


def discover_packages(start: str, names: Iterable[str]) -> list[str]:
    """Return package dirs under *start*, each containing a SPECS/*.spec.

    If *names* is non-empty, only those package directory names are returned.
    """
    if names:
        wanted = set(names)
        dirs = [p for p in os.listdir(start) if p in wanted]
    else:
        dirs = sorted(os.listdir(start))
    pkgs = []
    for name in dirs:
        path = os.path.join(start, name)
        if not os.path.isdir(path):
            continue
        if glob(os.path.join(path, "SPECS", "*.spec")):
            pkgs.append(name)
    return pkgs


def parse_explicit(spec: str) -> list[str]:
    """Every explicit BuildRequires entry from the spec, as an RPM requirement.

    A buildrequire may list several comma-separated capabilities and use a
    pkgconfig()/perl(...) form; those are kept verbatim. Bare names are stripped
    of any version constraint.
    """
    entries: list[str] = []
    with open(spec, encoding="utf-8") as fh:
        for line in fh:
            m = BUILDREQUIRE_RE.match(line)
            if not m:
                continue
            value = m.group(1).rstrip("\n")
            if value.startswith("%"):  # e.g. %{?...} macros
                continue
            for part in value.split(","):
                for dep in _split_part(part):
                    norm = _normalize_explicit(dep)
                    if norm:
                        entries.append(norm)
    return entries


def _split_part(part: str) -> list[str]:
    """Split one comma-part into one or more valid require strings.

    A BuildRequires line sometimes lists two bare names without a comma, e.g.
    "gcc gcc-c++" or "ntfs-3g ntfsprogs ntfs-3g-system-compression". Split on
    whitespace so each becomes its own requirement. Trailing junk that rpm
    would reject (e.g. a stray "}") is stripped.
    """
    part = part.strip()
    if not part or part.startswith("%"):
        return []
    # A part that starts with "/" (e.g. "/usr/bin/node") is a filesystem path,
    # not a package name — the whole thing is dropped rather than split into
    # usr / bin / node.
    if part.startswith("/"):
        return []
    # Drop a stray closing brace left over from a bad %{...} expansion.
    part = part.rstrip("}").strip()
    if not part:
        return []

    deps: list[str] = []
    # Strip a stray closing brace left over from a bad %{...} expansion, then
    # pull each name out of the part. A name with its version (e.g. the
    # pkgconfig(libicu-devel) >= 68 form split by whitespace) is captured as
    # one entry, so the version never becomes a stray token.
    for m in NAME_RE.findall(part):
        token = m[0] or m[1]
        if not token or VERSION_ONLY_RE.match(token):
            continue
        deps.append(token)
    return deps


def convert_implicit(out: str) -> list[str]:
    """Turn each capability emitted by %generate_buildrequires into an RPM
    requirement, preferring pkgconfig()/python3dist()/perl(...) forms.

    Uses _normalize_implicit so that:
    * python3dist(foo) → python3-foo (macro expanded)
    * pkgconfig(X-devel) → pkgconfig(X) (strip -devel)
    * bare names are normalized appropriately.
    """
    deps: list[str] = []
    for line in out.splitlines():
        for _, cap in DYN_RE.findall(line):
            base, arg = cap, ""
            if "(" in cap and cap.endswith(")"):
                base, arg = cap.split("(", 1)
                arg = arg[:-1]
            normalized = _normalize_implicit(f"{base}({arg})")
            if normalized:
                deps.append(normalized)
    return deps


def _normalize_explicit(dep: str) -> str:
    """Normalize an explicit buildrequire: strip version constraints, macros.

    Keeps pkgconfig(...), python3dist(...), perl(...) as written in spec.
    Does NOT convert python3dist→python3-* or strip -devel from pkgconfig.
    """
    if not dep or dep.startswith("%"):
        return ""
    dep = dep.split("%")[0].strip()
    dep = VERSION_RE.sub("", dep).strip()
    if not dep:
        return ""

    if dep.startswith("pkgconfig(") and dep.endswith(")"):
        inner = dep[len("pkgconfig("):-1]
        parts = inner.split(None, 1)
        name = parts[0]
        version = parts[1].strip() if len(parts) > 1 else ""
        if name.endswith("-devel"):
            name = name[: -len("-devel")]
        out = f"pkgconfig({name})"
        if version:
            out += f" {version}"
        return out

    if dep.startswith("python3dist(") and dep.endswith(")"):
        return f"python3-{dep[len('python3dist('):-1]}"

    if dep.startswith(("perl(", "pkgconfig64(", "xlib(")):
        return dep

    return dep


def _normalize_implicit(dep: str) -> str:
    """Normalize an implicit (auto-generated) buildrequire.

    * python3dist(foo) → python3-foo (macro-expanded package name)
    * pkgconfig(foo-devel) → pkgconfig(foo) (strip -devel for installability)
    * pkgconfig(foo) → pkgconfig(foo)
    * perl(...), pkgconfig64(...), xlib(...) → kept verbatim
    * bare names: stripped of version/macros
    """
    if not dep or dep.startswith("/") or dep.startswith("%"):
        return ""
    dep = dep.split("%")[0].strip()
    dep = VERSION_RE.sub("", dep).strip()
    if not dep:
        return ""

    if dep.startswith("pkgconfig(") and dep.endswith(")"):
        inner = dep[len("pkgconfig("):-1]
        parts = inner.split(None, 1)
        name = parts[0]
        version = parts[1].strip() if len(parts) > 1 else ""
        if name.endswith("-devel"):
            name = name[: -len("-devel")]
        out = f"pkgconfig({name})"
        if version:
            out += f" {version}"
        return out

    if dep.startswith("python3dist(") and dep.endswith(")"):
        return f"python3-{dep[len('python3dist('):-1]}"

    if dep.startswith(("perl(", "pkgconfig64(", "xlib(")):
        return dep

    return dep


def to_require(dep: str) -> str:
    """Normalise a single require entry to an RPM capability/package name.

    Uses explicit normalization (keep capability forms as-is, strip versions).
    For install checks we use implicit normalization to match rpm provides.
    """
    return _normalize_implicit(dep)


def dedupe(entries: list[str]) -> list[str]:
    """Dedupe while keeping the first occurrence of each normalised form."""
    seen: dict[str, str] = {}
    for dep in entries:
        key = to_require(dep).lower()
        if key and key not in seen:
            seen[key] = to_require(dep)
    return list(seen.values())


def is_installed(cap: str) -> bool:
    """True if a package already provides the requirement *cap*."""
    res = subprocess.run(
        ["rpm", "-q", "--whatprovides", cap],
        capture_output=True,
        text=True,
    )
    return res.returncode == 0


def resolve_package_root(explicit: str | None) -> str:
    """Return the mgarepo/ directory that holds the packages.

    Precedence:
      1. --root PATH if given.
      2. An existing mgarepo/ in the current working directory.
      3. Walk up from this script's location looking for mgarepo/.
    """
    if explicit:
        return os.path.abspath(explicit)

    cwd = os.getcwd()
    candidate = os.path.join(cwd, "mgarepo")
    if os.path.isdir(candidate):
        return candidate

    here = os.path.dirname(os.path.abspath(__file__))
    while True:
        pkg = os.path.join(here, "mgarepo")
        if os.path.isdir(pkg):
            return pkg
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    raise SystemExit(
        "Could not find mgarepo/. Pass it with --root PATH or run from "
        "a directory that has mgarepo/ as a child."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="don't install")
    parser.add_argument("pkgs", nargs="*", help="package directory names")
    parser.add_argument("--root", default=None,
                        help="mgarepo/ directory to scan (defaults to discovery)")
    parser.add_argument("--batch", type=int, default=20,
                        help="install every N unresolved deps (default: 20)")
    args = parser.parse_args()

    start = resolve_package_root(args.root)
    pkgs = discover_packages(start, args.pkgs)
    print(f"Discovered {len(pkgs)} package(s) under: {start}")

    unique: list[str] = []
    unique_pkgs = 0
    empty_pkgs = 0
    explicit_all: list[str] = []  # verbatim explicit deps
    implicit_all: list[str] = []  # macro-expanded implicit deps
    for name in pkgs:
        path = os.path.join(start, name)
        spec = next(iter(glob(os.path.join(path, "SPECS", "*.spec"))))
        explicit = parse_explicit(spec)
        work = tempfile.mkdtemp()
        try:
            proc = subprocess.run(
                ["rpmbuild", "-br", "--define", f"_topdir {path}", spec],
                capture_output=True, text=True,
                env={**os.environ, "RPMTOPDIR": work},
            )
        finally:
            subprocess.run(["rm", "-rf", work], check=False)
        implicit = convert_implicit(proc.stdout + proc.stderr)

        # Union per-package: keep explicit verbatim, implicit macro-expanded
        pkg_entries = explicit + implicit
        if not pkg_entries:
            empty_pkgs += 1
            print(f"  SKIP (no buildrequires): {name}")
            continue
        unique_pkgs += 1
        print(f"  {name}: {len(pkg_entries)} buildrequire(s) "
              f"({len(explicit)} explicit + {len(implicit)} implicit)")
        with open(os.path.join(path, "BR.captured"), "w") as fh:
            fh.write("\n".join(pkg_entries) + "\n")
        explicit_all.extend(explicit)
        implicit_all.extend(implicit)

    # Union across all packages: dedupe with implicit-normalization for
    # install checking, but preserve explicit form for output.
    # Build a map: implicit-normalized -> [forms]
    dep_map: dict[str, list[str]] = {}
    for dep in explicit_all + implicit_all:
        key = _normalize_implicit(dep).lower()
        if not key:
            continue
        norm_val = _normalize_implicit(dep)
        if norm_val:
            dep_map.setdefault(key, []).append(norm_val)

    # Pick one output form per normalized key, preferring python3-<pkg> forms.
    want: list[str] = []
    for key, forms in sorted(dep_map.items(), key=lambda kv: kv[0].lower()):
        chosen = forms[0]
        for f in forms:
            if f.startswith("python3-"):
                chosen = f
                break
        if chosen and chosen not in want:
            want.append(chosen)
    want = sorted(set(want), key=str.lower)

    out_path = os.path.join(start, "all_buildrequires.txt")
    with open(out_path, "w") as fh:
        fh.write("\n".join(want) + "\n")
    print(
        f"\nCaptured buildrequires from {unique_pkgs} package(s); "
        f"{empty_pkgs} with none.\n"
        f"Total unique buildrequires: {len(want)} -> {out_path}"
    )

    # Check installability using implicit normalization (matches rpm provides)
    unresolved = []
    installed = 0
    for dep in want:
        key = _normalize_implicit(dep)
        if is_installed(key):
            installed += 1
        else:
            unresolved.append(dep)
    print(f"\nAlready satisfied: {installed}/{len(want)}")
    print(f"Unresolved: {len(unresolved)}")

    if args.dry_run:
        print("\n== DRY RUN: would install these (batch %d) ==" % args.batch)
        for i in range(0, len(unresolved), args.batch):
            chunk = unresolved[i:i + args.batch]
            print(f"  batch {i // args.batch + 1}: " + " ".join(chunk))
        print("\n(No install performed.)")
        return 0

    if not unresolved:
        print("Nothing to install.")
        return 0

    # Install in batches of --batch deps, each via a single sudo urpmi call.
    # subprocess.run(list) passes each element as a separate argv, so
    # pkgconfig(...) parentheses and version specs are preserved literally.
    total_batches = (len(unresolved) + args.batch - 1) // args.batch
    for i in range(0, len(unresolved), args.batch):
        chunk = unresolved[i:i + args.batch]
        batch = i // args.batch + 1
        print(f"\n== Installing batch {batch}/{total_batches} ({len(chunk)} deps) ==")
        print(f"  $ sudo urpmi --auto " + " ".join(chunk))
        res = subprocess.run(["sudo", "urpmi", "--auto", *chunk])
        if res.returncode != 0:
            print(f"  batch {batch} exited {res.returncode}; continuing.",
                  file=sys.stderr)
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
