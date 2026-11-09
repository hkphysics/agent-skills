#!/usr/bin/env python3
"""
Mageia RPM generator.

Given a source RPM (local file or URL) or a Fedora dist-git package name,
extracts the spec, applies Mageia conventions, and builds a new RPM.

Usage:
    # From local SRPM
    python mageia_rpm_gen.py --srpm /path/to/pkg-1.0-1.fc40.src.rpm

    # From RPM URL (e.g., GitHub release)
    python mageia_rpm_gen.py --url https://github.com/.../pkg-1.0-1.x86_64.rpm

    # From Fedora dist-git package name
    python mageia_rpm_gen.py --fedora pkg-name

Options:
    -o, --output PATH       Output RPM path (default: ./RPMS/pkg-version-mga.rpm)
    -s, --spec-out PATH     Write modified spec to this path (optional)
    -k, --keep-build        Keep build directory after build
    --mock                  Build with mock instead of rpmbuild
    -g, --group GROUP       Mageia RPM group (see --list-groups)
    --list-groups           List available Mageia RPM groups and exit
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse


# Official Mageia RPM groups (from Mageia RPM groups policy)
# See: https://wiki.mageia.org/en/RPM_groups_policy
# These are used for the "Group:" tag in spec files and appear in rpmdrake categories
MAGEIA_GROUPS = [
    # Applications
    "Applications/Archiving",
    "Applications/CAD",
    "Applications/Communications",
    "Applications/Databases",
    "Applications/Editors",
    "Applications/Engineering",
    "Applications/File",
    "Applications/Graphics",
    "Applications/Internet",
    "Applications/Libraries",
    "Applications/Math",
    "Applications/Multimedia",
    "Applications/Office",
    "Applications/Publishing",
    "Applications/System",
    "Applications/Texttools",
    "Applications/Utilities",
    # Development
    "Development/Debuggers",
    "Development/Embedded",
    "Development/Interpreters",
    "Development/Languages",
    "Development/Libraries",
    "Development/Other",
    "Development/Tools",
    # Documentation
    "Documentation",
    # Graphical Desktop
    "Graphical desktop/Applications",
    "Graphical desktop/Enhancements",
    "Graphical desktop/Window Managers",
    # Hardware
    "Hardware/Arch",
    "Hardware/Devices",
    "Hardware/Drivers",
    "Hardware/PCMCIA",
    "Hardware/Video",
    # Libraries (system)
    "Libraries",
    # Networking
    "Networking/Communication",
    "Networking/DNS",
    "Networking/Information",
    "Networking/Internet",
    "Networking/News",
    "Networking/Tools",
    # System
    "System/Archiving",
    "System/Base",
    "System/Configuration",
    "System/Daemons",
    "System/Filesystems",
    "System/Kernel",
    "System/Libraries",
    "System/Shells",
    "System/Security",
    "System/Tools",
]


def run(cmd, cwd=None, check=True):
    """Run a command, return CompletedProcess."""
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        sys.exit(f"Command failed ({result.returncode}): {' '.join(cmd)}\n{result.stderr}")
    return result


def download(url, dest):
    """Download a file from URL to dest."""
    print(f"Downloading {url} ...")
    result = run(["wget", "-O", dest, url], check=False)
    if result.returncode != 0:
        sys.exit(f"Download failed: {result.stderr}")
    return dest


def extract_spec(rpm_path):
    """Extract spec file from an RPM/SRPM."""
    # Try rpm -q --specfile first (works for both binary and source RPMs)
    result = run(["rpm", "-q", "--specfile", rpm_path], check=False)
    if result.returncode == 0 and result.stdout.strip():
        spec_path = result.stdout.strip()
        if os.path.isfile(spec_path):
            return spec_path

    # Fallback: extract to temp dir and find .spec
    with tempfile.TemporaryDirectory() as tmpdir:
        run(["sh", "-c", f"cd {tmpdir} && rpm2cpio {rpm_path} | cpio -idmv"], check=False)
        for root, _, files in os.walk(tmpdir):
            for f in files:
                if f.endswith(".spec"):
                    return os.path.join(root, f)
    sys.exit(f"Could not extract spec from {rpm_path}")


def fetch_fedora_spec(package_name, dest_dir):
    """Clone Fedora dist-git and return path to .spec file."""
    repo_url = f"https://pkgs.fedoraproject.org/cgit/rpms/{package_name}.git"
    clone_dir = os.path.join(dest_dir, package_name)
    print(f"Cloning {repo_url} ...")
    result = run(["git", "clone", "--depth=1", repo_url, clone_dir], check=False)
    if result.returncode != 0:
        sys.exit(f"Failed to clone Fedora dist-git for {package_name}: {result.stderr}")

    # Find .spec file
    for f in os.listdir(clone_dir):
        if f.endswith(".spec"):
            return os.path.join(clone_dir, f)
    sys.exit(f"No .spec file found in {clone_dir}")


def parse_spec(spec_path):
    """Parse basic fields from spec file."""
    content = Path(spec_path).read_text()
    fields = {}
    for line in content.splitlines():
        m = re.match(r"^(\w+):\s*(.+)$", line)
        if m:
            fields[m.group(1).lower()] = m.group(2).strip()
    return fields, content


def apply_mageia_modifications(spec_content, overrides=None):
    """Apply Mageia-specific modifications to spec content."""
    overrides = overrides or {}
    lines = spec_content.splitlines()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Release:"):
            new_lines.append(overrides.get("release", "Release: 1%{?dist}"))
        elif stripped.startswith("Group:"):
            # Replace existing Group with our selected group
            if "group" in overrides:
                new_lines.append(f"Group: {overrides['group']}")
            else:
                new_lines.append(line)
        elif stripped.startswith("BuildRequires:"):
            # Replace Fedora-specific BuildRequires if needed
            if "fedora" in line.lower() or "rhel" in line.lower():
                continue  # drop for now; could be smarter
            new_lines.append(line)
        elif stripped.startswith("%define"):
            new_lines.append(line)
        else:
            new_lines.append(line)

    # Ensure %dist is defined (Mageia uses .mga)
    if not any("%dist" in l for l in new_lines):
        new_lines.insert(0, "%define dist .mga")

    # Add Group tag if not present and we have one
    if "group" in overrides:
        # Insert after Name: or at the beginning of the preamble
        for i, line in enumerate(new_lines):
            if line.strip().startswith("Name:"):
                new_lines.insert(i + 1, f"Group: {overrides['group']}")
                break
        else:
            new_lines.insert(0, f"Group: {overrides['group']}")

    return "\n".join(new_lines)


def build_rpm(spec_path, output_dir, use_mock=False, keep_build=False):
    """Build RPM from spec file."""
    os.makedirs(output_dir, exist_ok=True)

    if use_mock:
        result = run(["mock", "--rebuild", spec_path], cwd=output_dir, check=False)
    else:
        for d in ["BUILD", "RPMS", "SOURCES", "SPECS", "SRPMS", "BUILDROOT"]:
            os.makedirs(os.path.join(output_dir, d), exist_ok=True)

        spec_dir = os.path.dirname(spec_path)
        for item in os.listdir(spec_dir):
            if item != os.path.basename(spec_path):
                shutil.copy2(os.path.join(spec_dir, item), os.path.join(output_dir, "SOURCES", item))

        result = run([
            "rpmbuild", "-bb",
            "--define", f"_topdir {output_dir}",
            "--define", f"_sourcedir {output_dir}/SOURCES",
            spec_path
        ], check=False)

    if result.returncode != 0:
        sys.exit(f"Build failed:\n{result.stderr}")

    for root, _, files in os.walk(output_dir):
        for f in files:
            if f.endswith(".rpm") and not f.endswith(".src.rpm"):
                return os.path.join(root, f)
    sys.exit("No RPM found after build")


def list_groups():
    """Print available Mageia RPM groups."""
    print("Available Mageia RPM groups:")
    for g in sorted(MAGEIA_GROUPS):
        print(f"  {g}")


def main():
    parser = argparse.ArgumentParser(description="Generate a Mageia RPM from various sources.")

    # Source options - mutually exclusive but not required initially
    src = parser.add_mutually_exclusive_group(required=False)
    src.add_argument("--srpm", help="Path to local SRPM file")
    src.add_argument("--url", help="URL to binary or source RPM")
    src.add_argument("--fedora", help="Fedora package name (fetch from dist-git)")

    parser.add_argument("--list-groups", action="store_true", help="List available Mageia RPM groups and exit")

    parser.add_argument("-o", "--output", help="Output RPM path (default: ./RPMS/...)")
    parser.add_argument("-s", "--spec-out", help="Write modified spec to this path")
    parser.add_argument("-k", "--keep-build", action="store_true", help="Keep build directory")
    parser.add_argument("--mock", action="store_true", help="Build with mock instead of rpmbuild")
    parser.add_argument("--release", default="1%{?dist}", help="Release string (default: 1%{?dist})")
    parser.add_argument("-g", "--group", help="Mageia RPM group (see --list-groups)")

    args = parser.parse_args()

    if args.list_groups:
        list_groups()
        return

    # Now require one of the source options
    if not (args.srpm or args.url or args.fedora):
        parser.error("One of --srpm, --url, or --fedora is required")

    with tempfile.TemporaryDirectory() as workdir:
        spec_path = None

        if args.srpm:
            if not os.path.isfile(args.srpm):
                sys.exit(f"SRPM not found: {args.srpm}")
            spec_path = extract_spec(args.srpm)

        elif args.url:
            rpm_file = os.path.join(workdir, os.path.basename(urlparse(args.url).path))
            download(args.url, rpm_file)
            spec_path = extract_spec(rpm_file)

        elif args.fedora:
            spec_path = fetch_fedora_spec(args.fedora, workdir)

        # Read and modify spec
        fields, spec_content = parse_spec(spec_path)
        overrides = {"release": f"Release: {args.release}"}
        if args.group:
            overrides["group"] = args.group
        modified = apply_mageia_modifications(spec_content, overrides)

        # Write modified spec
        mod_spec = os.path.join(workdir, f"{fields.get('name', 'package')}.spec")
        Path(mod_spec).write_text(modified)
        print(f"Modified spec written to {mod_spec}")

        if args.spec_out:
            shutil.copy2(mod_spec, args.spec_out)
            print(f"Spec copied to {args.spec_out}")

        # Build
        build_dir = os.path.join(workdir, "build")
        rpm_path = build_rpm(mod_spec, build_dir, use_mock=args.mock, keep_build=args.keep_build)

        # Determine output path
        if args.output:
            out_path = args.output
        else:
            name = fields.get("name", "package")
            version = fields.get("version", "0.0")
            release = args.release.split("%")[0].strip()
            out_path = os.path.join(os.getcwd(), "RPMS", f"{name}-{version}-{release}.mga.x86_64.rpm")

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        shutil.move(rpm_path, out_path)
        print(f"✓ Built RPM: {out_path}")

        if args.keep_build:
            print(f"Build directory kept at: {build_dir}")


if __name__ == "__main__":
    main()
