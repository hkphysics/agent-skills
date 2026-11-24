#!/usr/bin/env python3
"""instbr.py — Resolve buildrequires for Mageia packages and install them.

Each package is processed one at a time: explicit BuildRequires are read from
the spec, implicit ones are captured from the generated SRPM (via bm -r), the
package's deps are deduped, checked against the installed rpm database, and
the unresolved ones are installed with sudo urpmi immediately — before moving
on to the next package. This way the script finds and installs deps as it goes
rather than deferring everything to a final batch.

Buildrequires come in two kinds:
  * explicit  — the static BuildRequires: lines in the spec. Kept as-is.
  * implicit  — capabilities emitted at build time by
                %generate_buildrequires / %pyproject_buildrequires. These are
                turned into an RPM capability requirement, preferring a
                pkgconfig(...) form (e.g. pkgconfig(udev)), a
                python3dist(...) form (e.g. python3dist(cloudpickle)),
                or a crate(...) form (e.g. crate(foo)) for Rust crates.

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
DYN_RE = re.compile(r"(python3dist|python3-|perl|cmake|pkgconfig|crate)\(([^)]+)\)")
# A buildrequire line: "BuildRequires: name, version" (one logical line may
# list several comma-separated capabilities).
BUILDREQUIRE_RE = re.compile(r"^BuildRequires:\s*(.+)$")
# Strip a version constraint, e.g. "pkg >= 1" -> "pkg".
VERSION_RE = re.compile(r"\s*(>=|<=|==|>|<)[^ ]*$")
# The capability emitted by %generate_buildrequires, with an optional
# version that may sit inside the parens (pkgconfig(libicu) >= 1.0), after it
# (pkgconfig(libicu) 1.0), or both. The parenthesised form matches the whole
# tag so the version never becomes a stray token; the version-only tail is
# dropped (e.g. the "1.0" in pkgconfig(libicu) >= 1.0).
CAPABILITY_RE = re.compile(
    r"(python3dist|python3-|perl|cmake|pkgconfig|pkgconfig64|xlib|crate)"
    r"\(([^)]+)\)\s*(?:>=|<=|==|>|<)?\s*[\d][\d.]*"
)
# The capability emitted by %generate_buildrequires, with an optional bare
# version that follows it with no operator, e.g. "rust >= 1.85" or
# "crate(chrono/default) 0.10.0". The bare-name branch keeps names that end in
# a symbol (gcc-c++) and drops a trailing version, keeping the rest of the
# tag inside the parens for crate()/pkgconfig(...) forms.
CAPABILITY2_RE = re.compile(
    r"(python3dist|python3-|perl|cmake|pkgconfig|pkgconfig64|xlib|crate)"
    r"\(([^)]+)\)\s*\d(?:[\d.]*)?"
)
# Used by _split_part to pull each name out of an explicit BuildRequires part.
# A capability like pkgconfig(name) >= 1.0 is captured whole (so its version
# never becomes a stray token), and bare names ending in a symbol (gcc-c++)
# are kept too.
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
    requirement.

    The generated BuildRequires (a crate()/python3dist()/pkgconfig(...)
    capability, possibly with a version that sits inside or after the parens)
    is pulled out with CAPABILITY_RE/CAPABILITY2_RE and normalised so the
    version is dropped and pkgconfig(...) names lose a trailing -devel, giving
    a bare capability such as crate(chrono/default) or python3-foo that rpm
    --whatprovides can match. Bare names (e.g. the "rust" in "rust >= 1.85")
    are skipped, as they come from the spec, not %generate_buildrequires.
    """
    deps: list[str] = []
    for line in out.splitlines():
        for prefix, cap in CAPABILITY_RE.findall(line):
            deps.append(_normalize_cap(prefix, cap))
        for prefix, cap in CAPABILITY2_RE.findall(line):
            deps.append(_normalize_cap(prefix, cap))
    return [d for d in deps if d]


def _normalize_cap(prefix: str, cap: str) -> str:
    """Normalise one generated capability for install checking.

    Drops the version, strips a trailing -devel from pkgconfig(name), and keeps
    the capability in its original form (e.g. python3dist(foo) -> python3dist(foo),
    pkgconfig(foo-devel) -> pkgconfig(foo), crate(chrono/default) -> crate(...)).
    The result is a capability string that urpmi can use to resolve via the
    RPM provides database; we do NOT convert python3dist(foo) to a Mageia package
    name like python3-foo.
    """
    cap = cap.strip()
    if not cap or cap.startswith("/"):
        return ""
    if prefix in ("pkgconfig", "pkgconfig64"):
        name = cap.split()[0]
        if name.endswith("-devel"):
            name = name[: -len("-devel")]
        return f"{prefix}({name})"
    if prefix == "python3dist":
        return f"python3dist({cap})"
    return f"{prefix}({cap})"


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
        out = f"pkgconfig({name})"
        if version:
            out += f" {version}"
        return out

    if dep.startswith("python3dist(") and dep.endswith(")"):
        return dep  # KEEP original capability form

    if dep.startswith("crate(") and dep.endswith(")"):
        return dep

    if dep.startswith(("perl(", "pkgconfig64(", "xlib(")):
        return dep

    return dep


def _normalize_implicit(dep: str) -> str:
    """Keep the original generated capability form without normalization.

    This is used for dedupe keys: we compare normalized forms so that
    equivalent deps are treated as the same, but install uses the raw form.
    """
    if not dep or dep.startswith("/") or dep.startswith("%"):
        return ""
    dep = dep.split("%")[0].strip()
    dep = VERSION_RE.sub("", dep).strip()
    if not dep:
        return ""

    # Keep original forms as-is for installability; dedupe keys are built
    # from these raw strings lowercased.
    if dep.startswith("pkgconfig(") and dep.endswith(")"):
        return dep
    if dep.startswith("python3dist(") and dep.endswith(")"):
        return dep
    if dep.startswith("crate(") and dep.endswith(")"):
        return dep
    if dep.startswith(("perl(", "pkgconfig64(", "xlib(")):
        return dep
    return dep


def to_require(dep: str) -> str:
    """Normalise a require entry for de-duplication and install checking.

    Uses implicit normalization (the one that matches rpm provides: versions
    dropped, pkgconfig -devel stripped, python3dist→python3-, crate tags kept
    verbatim) so identical requirements are treated as the same.
    """
    return _normalize_implicit(dep)


def dedupe(entries: list[str]) -> list[str]:
    """Dedupe while keeping the first occurrence of each normalized form.

    Normalization is now done only for comparison; the original form is kept.
    """
    seen: dict[str, str] = {}
    for dep in entries:
        key = _normalize_implicit(dep).lower()
        if key and key not in seen:
            seen[key] = dep
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

    for name in pkgs:
        path = os.path.join(start, name)
        spec = next(iter(glob(os.path.join(path, "SPECS", "*.spec"))))
        explicit = parse_explicit(spec)

        proc = subprocess.run(
            ["bm", "-r", "--move-srpm", ".", spec],
            capture_output=True, text=True, cwd=path,
            env={**os.environ, "RPMTOPDIR": tempfile.mkdtemp()},
        )
        srpm = (
            glob(os.path.join(path, "SRPMS", f"{os.path.splitext(os.path.basename(spec))[0]}-*.src.rpm"))
            or glob(os.path.join(path, "SRPMS", "*buildreqs.nosrc.rpm"))
            or glob(os.path.join(path, f"{os.path.splitext(os.path.basename(spec))[0]}-*.src.rpm"))
            or glob(os.path.join(path, "*buildreqs.nosrc.rpm"))
        )
        srpm = srpm[0] if srpm else None
        implicit = []
        if srpm:
            res = subprocess.run(
                ["rpm", "-q", "--requires", "-p", srpm],
                capture_output=True, text=True,
            )
            if res.returncode == 0:
                implicit = convert_implicit(res.stdout)
            subprocess.run(["rm", "-f", srpm], check=False)

        pkg_entries = explicit + implicit
        if not pkg_entries:
            print(f"  SKIP (no buildrequires): {name}")
            continue

        # Dedupe per-package
        pkg_entries = dedupe(pkg_entries)
        print(f"  {name}: {len(pkg_entries)} unique buildrequire(s)")

        # Check installability
        unresolved = []
        for dep in pkg_entries:
            key = _normalize_implicit(dep)
            if not is_installed(key):
                unresolved.append(dep)

        if not unresolved:
            print(f"  All deps already satisfied for {name}")
            continue

        print(f"  Unresolved for {name}: {len(unresolved)}")
        with open(os.path.join(path, "BR.captured"), "w") as fh:
            fh.write("\n".join(pkg_entries) + "\n")

        if args.dry_run:
            print(f"  DRY RUN: would install: {' '.join(unresolved)}")
            continue

        # Install in batches of --batch deps
        total_batches = (len(unresolved) + args.batch - 1) // args.batch
        for i in range(0, len(unresolved), args.batch):
            chunk = unresolved[i:i + args.batch]
            batch = i // args.batch + 1
            print(f"\n  == Installing batch {batch}/{total_batches} ({len(chunk)} deps) for {name} ==")
            print(f"    $ sudo urpmi --auto " + " ".join(chunk))
            res = subprocess.run(["sudo", "urpmi", "--auto", *chunk])
            if res.returncode != 0:
                print(f"    batch {batch} exited {res.returncode}; continuing.",
                      file=sys.stderr)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
