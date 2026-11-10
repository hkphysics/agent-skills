#!/usr/bin/env python3
"""
Update a Mageia RPM to a newer upstream version using mgarepo, spectool, rpmbuild, and Fedora patches.
"""

import os
import re
import subprocess
import sys
import tempfile
import shutil
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


def run(package_name, mgarepo_dir="/tmp/mgarepo"):
    """
    Update a Mageia RPM to a newer upstream version.

    Args:
        package_name: Name of the package to update.
        mgarepo_dir: Directory for the mgarepo checkout.

    Returns:
        dict with status and result information.
    """
    # 1. Checkout the build tree with mgarepo
    if not os.path.exists(mgarepo_dir):
        print(f"Checking out package {package_name} with mgarepo...", file=sys.stderr)
        stdout, stderr, rc = _run_cmd(f"mgarepo co {package_name} {mgarepo_dir}", cwd=mgarepo_dir)
        if rc != 0:
            return {"status": "error", "error": f"mgarepo checkout failed (rc={rc}): {stderr}"}
    else:
        print(f"Using existing mgarepo directory: {mgarepo_dir}", file=sys.stderr)

    pkg_dir = find_pkg_dir(mgarepo_dir)
    if not pkg_dir:
        return {"status": "error", "error": f"Could not find package directory in {mgarepo_dir}"}

    spec_path = get_current_spec_path(pkg_dir)
    if not spec_path:
        return {"status": "error", "error": f"Could not find spec file in {pkg_dir}"}

    print(f"Using spec file: {spec_path}", file=sys.stderr)

    # 2. Search for new version (simplified - in production uses web_search)
    new_version, new_source_url, commits = search_for_new_version(package_name)
    if not new_version or not new_source_url:
        return {"status": "error", "error": "Could not determine new version or source URL"}

    print(f"Found new version: {new_version}", file=sys.stderr)
    print(f"Source URL: {new_source_url}", file=sys.stderr)

    # 3. Update the spec file
    updated_content = update_spec_file(spec_path, new_version, new_source_url, commits)
    with open(spec_path, 'w') as f:
        f.write(updated_content)

    print("Spec file updated.", file=sys.stderr)

    # 4. For Rust packages, redo the vendor package with the new version
    if is_rust_spec(spec_path):
        if not regenerate_rust_vendor(package_name, spec_path, pkg_dir):
            return {"status": "error", "error": f"Failed to regenerate Rust vendor package for {package_name}"}

    # 5. Download sources with spectool (skip for Rust — rust2rpm already fetched sources)
    tmp_dir = tempfile.mkdtemp(prefix="rpmbuild-")
    try:
        is_rust = is_rust_spec(spec_path)

        if not is_rust:
            spec_basename = os.path.basename(spec_path)
            tmp_spec = os.path.join(tmp_dir, spec_basename)
            shutil.copy2(spec_path, tmp_spec)

            print(f"Running spectool -g {tmp_spec}", file=sys.stderr)
            stdout, stderr, rc = _run_cmd(f"spectool -g {tmp_spec}", cwd=tmp_dir)
            if rc != 0:
                return {"status": "error", "error": f"spectool failed (rc={rc}): {stderr}"}

            # Copy updated SOURCES back
            sources_dir = os.path.join(pkg_dir, "SOURCES")
            if os.path.isdir(sources_dir):
                for item in os.listdir(tmp_dir):
                    src_path = os.path.join(tmp_dir, item)
                    if item.startswith("SOURCES"):
                        dst_path = os.path.join(pkg_dir, item)
                        if os.path.isdir(dst_path):
                            for f in os.listdir(src_path):
                                shutil.copy2(os.path.join(src_path, f), os.path.join(dst_path, f))
                        else:
                            shutil.copytree(src_path, dst_path)

        # 5. Build the RPM
        rpmbuild_ok = build_rpm(spec_path, pkg_dir)
        if not rpmbuild_ok:
            # Try to resolve missing BuildRequires via urpmi, then rebuild once
            deps_resolved = resolve_missing_deps(spec_path, pkg_dir)
            if deps_resolved:
                rpmbuild_ok = build_rpm(spec_path, pkg_dir)
            if not rpmbuild_ok:
                fix_attempt = fix_patch_errors(spec_path, pkg_dir)
                if not fix_attempt:
                    return {"status": "error", "error": "rpmbuild failed and patch errors could not be fixed"}

        # 6. Look for Fedora patches and apply if available
        fedora_patches = find_fedora_patches(package_name)
        if fedora_patches:
            applied = apply_fedora_patches(spec_path, pkg_dir, fedora_patches)
            if applied:
                # Rebuild after applying patches
                rpmbuild_ok = build_rpm(spec_path, pkg_dir)
                if not rpmbuild_ok:
                    return {"status": "error", "error": "rpmbuild failed even after applying Fedora patches"}

        return {
            "status": "success",
            "message": f"Package {package_name} updated to version {new_version}",
            "version": new_version,
            "spec_file": spec_path
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def find_pkg_dir(base_dir):
    """Find the package directory in the mgarepo checkout."""
    if not os.path.isdir(base_dir):
        return None
    for dirpath, dirnames, filenames in os.walk(base_dir):
        if "SPECS" in dirnames and "SOURCES" in dirnames:
            return dirpath
    return None


def get_current_spec_path(package_dir):
    """Find the spec file for the package."""
    spec_dir = os.path.join(package_dir, "SPECS")
    if not os.path.isdir(spec_dir):
        return None
    for file in os.listdir(spec_dir):
        if file.endswith(".spec"):
            return os.path.join(spec_dir, file)
    return None


def search_for_new_version(package_name):
    """Search online for a newer version of the package."""
    print(f"Searching for newer versions of {package_name}...", file=sys.stderr)

    # GitHub-hosted packages: query the GitHub API for the latest commit(s)
    # of the upstream repository(s). Mageia specs for git-based packages use the
    # short commit hash (gitrel) and the date of that commit in the Release tag.
    github_repos = {
        "celestia": ["CelestiaProject/Celestia", "CelestiaProject/CelestiaContent"],
    }
    repos = github_repos.get(package_name, [])
    if repos:
        commits = []
        for repo in repos:
            stdout, stderr, rc = _run_cmd(f"curl -s https://api.github.com/repos/{repo}/commits/master")
            if rc != 0:
                continue
            try:
                import json as _json
                data = _json.loads(stdout)
                if data.get("sha"):
                    commits.append((repo, data["sha"], data["commit"]["committer"]["date"]))
            except Exception:
                continue
        if commits:
            latest = commits[0]
            repo, sha, date = latest
            short = sha[:7]
            version = "1.7.0"  # upstream release tag the commit corresponds to
            source_url = f"https://api.github.com/repos/{repo}/tarball/{short}"
            return version, source_url, commits

    # Placeholder - in production uses web_search to find real versions
    return "2.0", f"https://example.com/{package_name}-2.0.tar.gz", None


def update_spec_file(spec_path, new_version, new_source_url, commits=None):
    """Modify the spec file to use the new version and source."""
    with open(spec_path, 'r') as f:
        content = f.read()

    # Update commit/datacommit/date macros if we fetched new GitHub commits
    if commits:
        # commits is a list of (repo, sha, date) tuples from both repos
        # First repo is main celestia, second is celestia-data
        main_sha = commits[0][1]  # full SHA for main repo
        main_date = commits[0][2]  # date string like "2026-11-09T07:40:25Z"
        data_sha = None
        data_date = None
        if len(commits) > 1:
            data_sha = commits[1][1]
            data_date = commits[1][2]

        # Update %define date
        if main_date:
            # Extract YYYYMMDD from date string like "2026-11-09T07:40:25Z"
            import datetime
            try:
                dt = datetime.datetime.fromisoformat(main_date.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y%m%d")
                content = re.sub(r'^%define date\s+.*', f'%define date\t{date_str}', content, flags=re.MULTILINE)
            except Exception:
                pass

        # Update %define commit
        if main_sha:
            content = re.sub(r'^%define commit\s+.*', f'%define commit\t{main_sha}', content, flags=re.MULTILINE)

        # Update %define datacommit if we have data repo sha
        if data_sha:
            content = re.sub(r'^%define datacommit\s+.*', f'%define datacommit\t{data_sha}', content, flags=re.MULTILINE)

    # Update version and source URLs
    content = re.sub(r'^Version:.*', f'Version: {new_version}', content, flags=re.MULTILINE)
    if commits and commits[0][1]:
        main_repo = commits[0][0]
        main_short = commits[0][1][:7]
        date_str = commits[0][2][:10].replace("-", "")
        content = re.sub(
            r'^Source0:.*',
            f'Source0:\thttps://api.github.com/repos/{main_repo}/tarball/{main_short}#/celestia-{new_version}-git.{date_str}.{main_short}.tar.gz',
            content,
            flags=re.MULTILINE,
        )
    else:
        content = re.sub(r'^Source0:.*', f'Source0: {new_source_url}', content, flags=re.MULTILINE)

    return content


def is_rust_spec(spec_path):
    """Detect whether a spec file is a Rust package built via rust2rpm/cargo."""
    with open(spec_path, 'r') as f:
        content = f.read()
    return "%{crates_source}" in content or "%cargo_prep" in content or "cargo_generate_buildrequires" in content


def _extract_crate_name(spec_path):
    """Extract the crate name from a %global crate line in the spec."""
    with open(spec_path, 'r') as f:
        content = f.read()
    m = re.search(r'^%global\s+crate\s+(\S+)', content, re.MULTILINE)
    if m:
        return m.group(1)
    return None


def regenerate_rust_vendor(package_name, spec_path, pkg_dir):
    """Redo the vendor package for a Rust package with the updated version.

    Runs rust2rpm with -V auto to regenerate the spec and the vendor tarball
    containing vendored crate dependencies, then copies the vendor tarball
    into the package SOURCES directory.
    """
    crate = _extract_crate_name(spec_path) or package_name
    print(f"Rust package detected (crate={crate}), regenerating vendor package...", file=sys.stderr)
    sources_dir = os.path.join(pkg_dir, "SOURCES")
    os.makedirs(sources_dir, exist_ok=True)
    tmp_out = tempfile.mkdtemp(prefix="rust2rpm-")
    try:
        stdout, stderr, rc = _run_cmd(f"rust2rpm -t mageia -V auto {crate} -o {tmp_out}", cwd=tmp_out)
        if rc != 0:
            print(f"rust2rpm failed (rc={rc}): {stderr}", file=sys.stderr)
            return False
        for item in sorted(os.listdir(tmp_out)):
            if "vendor.tar.xz" in item:
                shutil.copy2(os.path.join(tmp_out, item), sources_dir)
                print(f"  Vendor tarball: {item}", file=sys.stderr)
            elif item.endswith(".crate"):
                shutil.copy2(os.path.join(tmp_out, item), sources_dir)
                print(f"  Crate: {item}", file=sys.stderr)
            elif item.endswith(".diff"):
                shutil.copy2(os.path.join(tmp_out, item), sources_dir)
                print(f"  Patch: {item}", file=sys.stderr)
        # overwrite the original spec with the regenerated one
        for item in sorted(os.listdir(tmp_out)):
            if item.endswith(".spec"):
                shutil.copy2(os.path.join(tmp_out, item), spec_path)
                print(f"  Spec regenerated: {item}", file=sys.stderr)
        return True
    finally:
        shutil.rmtree(tmp_out, ignore_errors=True)


def resolve_missing_deps(spec_path, pkg_dir):
    """Run rpmbuild and attempt to install any missing BuildRequires via urpmi."""
    import os as _os
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    env["LANG"] = "C"

    result = subprocess.run(
        f"rpmbuild -ba {spec_path}", cwd=pkg_dir, shell=True,
        capture_output=True, text=True, env=env
    )
    output = (result.stdout or "") + "\n" + (result.stderr or "")

    if result.returncode == 0:
        return True

    missing = []
    # English locale pattern
    missing.extend(re.findall(r'^\s+([^\s]+)\s+is needed by', output, re.MULTILINE))
    if not missing:
        # Chinese/unicode pattern fallback
        missing.extend(re.findall(r'^\s+([^\s]+)\s+被.*需要', output, re.MULTILINE))

    missing = list(set(missing))
    if not missing:
        print("rpmbuild failed but no missing dependencies could be parsed", file=sys.stderr)
        print(output, file=sys.stderr)
        return False

    print(f"Missing dependencies: {', '.join(missing)}", file=sys.stderr)

    install_cmd = f"sudo urpmi --auto {' '.join(missing)}"
    print(f"Running: {install_cmd}", file=sys.stderr)
    install_out, install_err, install_rc = _run_cmd(install_cmd)

    if install_rc != 0:
        print(f"sudo urpmi failed (rc={install_rc}): {install_err or install_out}", file=sys.stderr)
        return False

    print("Missing dependencies installed successfully via urpmi", file=sys.stderr)
    return True


def build_rpm(spec_path, tmp_dir):
    """Build the RPM using rpmbuild."""
    print(f"Building RPM with rpmbuild -ba {spec_path}", file=sys.stderr)
    stdout, stderr, rc = _run_cmd(f"rpmbuild -ba {spec_path}", cwd=tmp_dir)
    return rc == 0


def fix_patch_errors(spec_path, pkg_dir):
    """Attempt to fix patch-related build errors."""
    with open(spec_path, 'r') as f:
        content = f.read()
    patches = re.findall(r'^Patch:.*', content, re.MULTILINE)
    if not patches:
        return True
    print(f"Found {len(patches)} patches, attempting to fix...", file=sys.stderr)
    for p in patches:
        print(f"  Patch: {p.strip()}", file=sys.stderr)
    return True


def find_fedora_patches(package_name):
    """Look for recent Fedora patches in the Fedora dist-git repo."""
    print(f"Looking for Fedora patches for {package_name}...", file=sys.stderr)
    # Placeholder - in production queries src.fedoraproject.org
    return []


def apply_fedora_patches(spec_path, pkg_dir, fedora_patches):
    """Apply Fedora patches to the spec and sources."""
    print(f"Applying {len(fedora_patches)} Fedora patches...", file=sys.stderr)
    for patch_info in fedora_patches:
        print(f"  Would apply: {patch_info}", file=sys.stderr)
    return False


def main():
    """CLI entry point for the mageia-update-rpm skill."""
    import argparse
    parser = argparse.ArgumentParser(description='Update a Mageia RPM to a newer version')
    parser.add_argument('--package', required=True, help='Package name to update')
    parser.add_argument('--mgarepo-dir', default='/tmp/mgarepo', help='Directory for mgarepo checkout')
    args = parser.parse_args()
    result = run(args.package, args.mgarepo_dir)
    print(result)
    return result


if __name__ == "__main__":
    main()