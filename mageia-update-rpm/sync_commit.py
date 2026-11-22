#!/usr/bin/env python3
"""
Sync and commit built Mageia RPM packages.

For each package:
1. Check if RPMs were built successfully
2. Run 'svn diff' to show changes
3. Ask user whether to sync and commit
4. If yes: run 'mgarepo sync' then 'mgarepo commit' with message "updated to <version>"
"""

import os
import re
import subprocess
import sys
import argparse
from pathlib import Path


def _run_cmd(cmd, cwd=None):
    """Run a shell command, return (stdout, stderr, returncode)."""
    try:
        result = subprocess.run(
            cmd, cwd=cwd, shell=True, capture_output=True, text=True, check=False
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except Exception as e:
        return "", str(e), 1


def _get_spec_version(spec_path):
    """Extract Version: and Release: from spec file."""
    with open(spec_path, 'r') as f:
        content = f.read()
    version_match = re.search(r'^Version:\s+(\S+)', content, re.MULTILINE)
    release_match = re.search(r'^Release:\s+(\S+)', content, re.MULTILINE)
    version = version_match.group(1) if version_match else "unknown"
    release = release_match.group(1) if release_match else "unknown"
    # Clean up macro like %mkrel -> 1 (just use release number without macro suffix)
    release_clean = release.replace('%mkrel', '1') if release and '%' in release else release
    return version, release_clean


def _has_built_rpms(pkg_dir):
    """Check if package has successfully built RPMs in RPMS/ and SRPMS/."""
    rpms_dir = Path(pkg_dir) / "RPMS"
    srpms_dir = Path(pkg_dir) / "SRPMS"
    has_rpms = any(rpms_dir.rglob("*.rpm")) if rpms_dir.exists() else False
    has_srpms = any(srpms_dir.rglob("*.rpm")) if srpms_dir.exists() else False
    return has_rpms and has_srpms


def _get_spec_path(pkg_dir):
    """Find the spec file in the package directory."""
    spec_dir = Path(pkg_dir) / "SPECS"
    if not spec_dir.exists():
        return None
    for spec_file in spec_dir.glob("*.spec"):
        return spec_file
    return None


def _svn_diff(pkg_dir):
    """Run svn diff in the package directory."""
    stdout, stderr, rc = _run_cmd("svn diff", cwd=pkg_dir)
    if rc != 0:
        return f"svn diff failed (rc={rc}): {stderr}"
    return stdout or "(no changes)"


def _mgarepo_sync(pkg_dir):
    """Run mgarepo sync in the package directory (before commit)."""
    print(f"  Running: mgarepo sync", file=sys.stderr)
        # Remove stale sha1.lst before commit to avoid committing old hashes
    sha1_path = Path(pkg_dir) / "SOURCES" / "sha1.lst"
    if sha1_path.exists():
        try:
            sha1_path.unlink()
            print(f"  Removed sha1.lst from SOURCES/", file=sys.stderr)
        except Exception as e:
            print(f"  Warning: could not remove sha1.lst: {e}", file=sys.stderr)
    stdout, stderr, rc = _run_cmd("mgarepo sync", cwd=pkg_dir)
    if rc != 0:
        return False, f"mgarepo sync failed (rc={rc}): {stderr}"
    return True, stdout


def _mgarepo_submit(pkg_dir):
    """Run mgarepo submit in the package directory."""
    print(f"  Running: mgarepo submit", file=sys.stderr)
    stdout, stderr, rc = _run_cmd("mgarepo submit", cwd=pkg_dir)
    if rc != 0:
        return False, f"mgarepo submit failed (rc={rc}): {stderr}"
    return True, stdout


def _mgarepo_commit(pkg_dir, message):
    """Run mgarepo ci with the given message in the package directory."""
    print(f"  Running: mgarepo ci -m '{message}'", file=sys.stderr)
    # Use mgarepo ci (commit) with the message
    stdout, stderr, rc = _run_cmd(f"mgarepo ci -m '{message}'", cwd=pkg_dir)
    if rc != 0:
        return False, f"mgarepo ci failed (rc={rc}): {stderr}"
    return True, stdout


def _is_already_submitted(pkg_name):
    """Check if package is already submitted/built on pkgsubmit.mageia.org.
    Returns True if found, False if not found, None if check failed (network error etc)."""
    url = f"https://pkgsubmit.mageia.org/?q={pkg_name}"
    try:
        stdout, stderr, rc = _run_cmd(f"curl -sL --max-time 10 '{url}'")
        if rc == 0:
            # If the package name appears as a submitted package link, it is already submitted
            # Package links look like: class="package">conmon-2.2.1-1.mga11
            import re
            pkg_links = re.findall(r'class="package">[^<]+', stdout)
            for link in pkg_links:
                # Check if link starts with pkg_name- (package name prefix before version)
                cleaned = link.replace('class="package">', '')
                if cleaned.startswith(pkg_name + '-'):
                    return True
            return False
        return False
    except Exception:
        return None


def _offer_submit(pkg_dir, pkg_name, version, release, commit_msg):
    """Ask the user whether to run mgarepo submit. Returns the result dict."""
    # Check if package is already available on pkgsubmit.mageia.org
    already = _is_already_submitted(pkg_name)
    if already is True:
        print(f"  {pkg_name} {version}-{release} already appears submitted on pkgsubmit.mageia.org — skipping submit.")
        return {
            "package": pkg_name,
            "status": "submitted",
            "version": version,
            "release": release,
            "commit_message": commit_msg,
            "submitted": True,
            "already_submitted": True,
        }
    elif already is None:
        print(f"  Could not check pkgsubmit.mageia.org (network error) — proceeding to prompt.")

    try:
        submit_response = input(f"\nRun mgarepo submit for {pkg_name} {version}-{release} now? [y/N/q]: ").strip().lower()
    except EOFError:
        submit_response = 'n'

    submitted = False
    if submit_response in ('y', 'yes'):
        ok, out = _mgarepo_submit(pkg_dir)
        if not ok:
            return {"package": pkg_name, "status": "error", "error": out, "version": version, "release": release, "commit_message": commit_msg}
        print(f"  mgarepo submit: OK")
        submitted = True
    elif submit_response in ('q', 'quit'):
        return {"package": pkg_name, "status": "quit"}

    return {
        "package": pkg_name,
        "status": "submitted" if submitted else "committed",
        "version": version,
        "release": release,
        "commit_message": commit_msg,
        "submitted": submitted
    }


def process_package(pkg_name, mgarepo_root):
    """Process a single package: check build, show diff, prompt for sync/commit."""
    pkg_dir = Path(mgarepo_root) / pkg_name
    if not pkg_dir.exists():
        return {"package": pkg_name, "status": "error", "error": f"Package directory not found: {pkg_dir}"}

    spec_path = _get_spec_path(pkg_dir)
    if not spec_path:
        return {"package": pkg_name, "status": "error", "error": f"No spec file found in {pkg_dir}/SPECS/"}

    version, release = _get_spec_version(spec_path)

    if not _has_built_rpms(pkg_dir):
        return {
            "package": pkg_name,
            "status": "skip",
            "reason": f"No built RPMs found (RPMS/ and/or SRPMS/ empty)",
            "version": version,
            "release": release
        }

    print(f"\n{'='*60}")
    print(f"Package: {pkg_name}")
    print(f"Version: {version}-{release}")
    print(f"Directory: {pkg_dir}")
    print(f"{'='*60}")

    # Show svn diff
    diff = _svn_diff(pkg_dir)
    print(f"\n--- svn diff ---")
    print(diff)

    # If there are no changes, skip sync/commit and go straight to submit
    if diff.strip() in ("", "(no changes)"):
        print(f"\nNo changes for {pkg_name} {version}-{release} — skipping sync and commit.")
        commit_msg = f"updated to {version}"
        return _offer_submit(pkg_dir, pkg_name, version, release, commit_msg)

    # Prompt user
    while True:
        try:
            response = input(f"\nSync and commit {pkg_name} {version}-{release}? [y/N/q]: ").strip().lower()
        except EOFError:
            response = 'n'
        if response in ('y', 'yes'):
            # Run mgarepo sync
            ok, out = _mgarepo_sync(pkg_dir)
            if not ok:
                return {"package": pkg_name, "status": "error", "error": out, "version": version, "release": release}
            print(f"  mgarepo sync: OK")

            # Run mgarepo commit
            commit_msg = f"updated to {version}"
            ok, out = _mgarepo_commit(pkg_dir, commit_msg)
            if not ok:
                return {"package": pkg_name, "status": "error", "error": out, "version": version, "release": release}
            print(f"  mgarepo ci: OK (message: '{commit_msg}')")

            return _offer_submit(pkg_dir, pkg_name, version, release, commit_msg)

        elif response in ('n', 'no', ''):
            return {
                "package": pkg_name,
                "status": "skipped",
                "reason": "User declined",
                "version": version,
                "release": release
            }
        elif response in ('q', 'quit'):
            return {"package": pkg_name, "status": "quit"}
        else:
            print("Please enter 'y', 'n', or 'q'")


def main():
    parser = argparse.ArgumentParser(
        description='Sync and commit built Mageia RPM packages',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s python-stdnum rust-fd-find libpqxx
  %(prog)s --all
  %(prog)s --file packages.txt
        """
    )
    parser.add_argument('packages', nargs='*', help='Package names to process')
    parser.add_argument('--all', action='store_true', help='Process all packages with built RPMs')
    parser.add_argument('--file', '-f', help='Read package list from file (one per line)')
    parser.add_argument('--mgarepo-root', default='/home/joe/bench/git/agent-skills/mgarepo',
                        help='Root directory containing package subdirectories')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without committing')

    args = parser.parse_args()

    mgarepo_root = Path(args.mgarepo_root)
    if not mgarepo_root.exists():
        print(f"Error: mgarepo root not found: {mgarepo_root}", file=sys.stderr)
        sys.exit(1)

    # Determine package list
    if args.all:
        pkg_names = [d.name for d in mgarepo_root.iterdir()
                     if d.is_dir() and (d / "SPECS").exists()]
    elif args.file:
        with open(args.file) as f:
            pkg_names = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    elif args.packages:
        pkg_names = args.packages
    else:
        # No explicit packages given: auto-discover packages with built RPMs
        print("No packages specified. Auto-discovering packages with built RPMs...")
        pkg_names = []
        for d in mgarepo_root.iterdir():
            if d.is_dir() and (d / "SPECS").exists():
                if _has_built_rpms(d):
                    pkg_names.append(d.name)
        if not pkg_names:
            print("No packages with built RPMs found.")
            sys.exit(0)
        print(f"Found {len(pkg_names)} package(s) with built RPMs: {', '.join(pkg_names)}")

    print(f"Processing {len(pkg_names)} package(s) from {mgarepo_root}")
    print(f"Mode: {'dry-run' if args.dry_run else 'interactive'}")

    results = []
    for i, pkg_name in enumerate(pkg_names, 1):
        print(f"\n[{i}/{len(pkg_names)}] Checking {pkg_name}...")
        result = process_package(pkg_name, mgarepo_root)
        results.append(result)

        if result.get("status") == "quit":
            print("\nUser requested quit. Stopping.")
            break

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for r in results:
        status = r.get("status", "unknown")
        pkg = r.get("package", "?")
        if status == "committed":
            print(f"  ✓ {pkg} {r.get('version')}-{r.get('release')} -> committed")
        elif status == "submitted":
            print(f"  ✓ {pkg} {r.get('version')}-{r.get('release')} -> committed (submitted)")
        elif status == "skipped":
            print(f"  ⊘ {pkg} {r.get('version')}-{r.get('release')} -> skipped ({r.get('reason')})")
        elif status == "skip":
            print(f"  - {pkg} {r.get('version')}-{r.get('release')} -> {r.get('reason')}")
        elif status == "error":
            print(f"  ✗ {pkg} -> ERROR: {r.get('error')}")
        elif status == "quit":
            print(f"  ⏹ {pkg} -> quit requested")

    committed = sum(1 for r in results if r.get("status") in ("committed", "submitted"))
    print(f"\nTotal committed: {committed}/{len(results)}")


if __name__ == "__main__":
    main()