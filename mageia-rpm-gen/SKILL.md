---
name: mageia-rpm-gen
description: Generate Mageia RPMs from various sources (SRPM, URL, or Fedora dist-git) with Mageia conventions.
---

# Mageia RPM Generator

Build a Mageia-compatible RPM from various sources: local SRPM, URL, or Fedora dist-git package name.

## Usage

```bash
# From local SRPM
python mageia_rpm_gen.py --srpm /path/to/pkg-1.0-1.fc40.src.rpm

# From RPM URL (e.g., GitHub release)
python mageia_rpm_gen.py --url https://github.com/.../pkg-1.0-1.x86_64.rpm

# From Fedora dist-git package name
python mageia_rpm_gen.py --fedora pkg-name

# List available Mageia RPM groups
python mageia_rpm_gen.py --list-groups

# Build with a specific Mageia group
python mageia_rpm_gen.py --srpm pkg.src.rpm -g Applications/Graphics
```

## Options

| Option | Description |
|--------|-------------|
| `--srpm PATH` | Path to local SRPM file |
| `--url URL` | URL to binary or source RPM |
| `--fedora NAME` | Fedora package name (fetch from dist-git) |
| `-o, --output PATH` | Output RPM path (default: `./RPMS/...`) |
| `-s, --spec-out PATH` | Write modified spec to this path |
| `-k, --keep-build` | Keep build directory after build |
| `--mock` | Build with mock instead of rpmbuild |
| `--release STR` | Release string (default: `1%{?dist}`) |
| `-g, --group GROUP` | Mageia RPM group (see `--list-groups`) |
| `--list-groups` | List available Mageia RPM groups and exit |

## Mageia RPM Groups

The script includes the official Mageia RPM groups (from the [RPM groups policy](https://wiki.mageia.org/en/RPM_groups_policy)). Use `--list-groups` to see all available groups.

Common groups for applications:
- `Applications/Graphics`
- `Applications/Internet`
- `Applications/Multimedia`
- `Applications/Office`
- `Applications/Utilities`
- `Applications/Texttools`

## What it does

1. Extracts the spec file from the source (SRPM, URL, or Fedora dist-git)
2. Applies Mageia-specific modifications:
   - Sets `Release: 1%{?dist}`
   - Sets `%define dist .mga`
   - Adds or replaces the `Group:` tag with the specified Mageia group
   - Drops Fedora-specific `BuildRequires:` lines
3. Builds the RPM using `rpmbuild` (or `mock` if `--mock` is specified)

## Dependencies

- `rpm`, `rpmbuild`, `wget`, `git` commands must be available in the PATH
- For `--mock`: `mock` command must be available

## Location

The script is at `~/.pi/agent/extensions/mageia_rpm_gen.py`.