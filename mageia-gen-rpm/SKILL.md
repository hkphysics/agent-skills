---
name: mageia-rpm-gen
description: Generate Mageia RPMs from various sources (SRPM, URL, or Fedora dist-git) with Mageia conventions, using an SRPM-first workflow.
---

# Mageia RPM Generator

Build a Mageia-compatible RPM from various sources: local SRPM, URL, or Fedora dist-git package name.

## Instructions
* **Never invoke `rpmbuild` directly — always use `bm`, even for diagnostics.** `bm` builds inside the `<mgarepo>/<package>/` layout and reads the correct `SPECS/`/`SOURCES/`, writing `BUILD/`, `RPMS/`, `SRPMS/` there. A bare `rpmbuild -ba/-bp/-bb` writes to `~/rpmbuild` and looks in `~/rpmbuild/SOURCES`, so it uses the wrong source tree and the wrong output location. To investigate a failure, read the log `SPECS/log.<package>` that `bm` writes, or re-run `bm -p SPECS/<package>.spec` (prep) / `bm -r SPECS/<package>.spec` (prep only) / `bm SPECS/<package>.spec` (full build). Never type `rpmbuild ...` by hand; `bm` calls `rpmbuild` internally, which is fine.
* All checkouts and builds live under a single parent directory named
  `mgarepo`. See "Build location" below.


## Workflow
1. The build should in in Build location.  The name of the package
   should be from the SPEC file or using standard mageia conventions
2. **Search first.** Before creating any RPM, search the web, the
   github, Fedora and Opensuse  repositories, and rpmfind.net to see whether
   an SRPM (or spec) for the same version already 
   exists. Reuse it directly and convert it to Mageia instead of
   writing a spec from scratch.
3. If there is a Fedora or Opensuse SRPM for the package then attempt
   convert that SRPM to Mageia conventions
4. If there is no SPEC and the file is a rust crate then
   generate the spec file using rust2rpm and if python use pyp2rpm
5. Use spectool to pull the source files into the SOURCES
6. Do a test build with bm

## Build location

Everything for one package lives under a single parent directory named `mgarepo`:

```
<mgarepo>/                <- parent directory (created if missing)
  <package>/              <- one subdirectory per package
    SPECS/<package>.spec
    SOURCES/
```
     This creates `mgarepo/<package>/` containing the SPECS/ and SOURCES/ layout from Mageia's package repository.
   - Stop if the package does not exist in the Mageia repository.
   - `cd` into `mgarepo/<package>/`; all following steps assume this working directory.
   - Never run `mgarepo co` from a directory outside the mgarepo
    parent — it must be run from inside the mgarepo directory itself.

## Usage

```bash
# From local SRPM
python mageia_rpm_gen.py --srpm /path/to/pkg-1.0-1.mga11.src.rpm

# From RPM URL (e.g., GitHub release)
python mageia_rpm_gen.py --url https://github.com/.../pkg-1.0-1.x86_64.rpm

# From Fedora dist-git package name
python mageia_rpm_gen.py --fedora pkg-name

# List available Mageia RPM groups
python mageia_rpm_gen.py --list-groups

# Build with a specific Mageia group
python mageia_rpm_gen.py --srpm pkg.src.rpm -g Applications/Graphics
```
## SRPM conventions
1. SRPMS should contain all source code necessary to build a binary
   RPM without additional downloads

## Libraries
1. When converting to mageia specs make sure that the SRPM uses mageia
   libraries.
2. **Never hardcode library directory paths** such as `/usr/lib64` or `/usr/lib` — use the `%{_libdir}` macro (e.g. `/usr/lib64` on x86_64, `/usr/lib` on ARM). The same applies to any other filename component: build tags, archive names, package names, URLs, etc. Write them with macros (`%{version}`, `%{name}`, `%{url}`, `%{built_tag}`, `%{shortcommit}`) rather than literal values — see "Mageia Library Conventions" above and "Spec macros" below.

## Rust Source RPMs and Vendored Sources

When generating an RPM from Rust, the source RPM must include a **vendor package** containing the vendored crate dependencies.

1. Generate a Rust spec with vendored dependencies and a vendor tarball:
   ```bash
   rust2rpm -t mageia -V auto <crate>
   ```
   This produces a spec file plus a vendor tarball (e.g. `eza-0.23.4-vendor.tar.xz`).

Because the vendored sources tarball is carried inside the source RPM, the binary RPM build runs fully offline (vendored sources only).

## Mageia Library Conventions

The generated RPMs must follow Mageia conventions regarding libraries:

- Shared libraries are named with the `lib` prefix and placed in the library directory (`%{_libdir}`, e.g. `/usr/lib64`).
- Library packages are grouped under the library groups (e.g. `Libraries`, `Development/Libraries`).
- Binary packages that link against a shared library must declare `Requires:` for the library package (or the equivalent bundled/provided name) instead of relying on the library being installed implicitly.
- Rust crates that provide a library produce library subpackages alongside the binary subpackage; crates that only provide a library produce no binary subpackage.

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
3. Generates the source RPM with `rpmbuild -bs`.
4. Builds the binary RPM from the source RPM with `rpmbuild --rebuild <srpm>`.

## Dependencies

- `rpm`, `bm`, `wget`, `git` commands must be available in the PATH
- For `--mock`: `mock` command must be available

## Location

The script is at `~/.pi/agent/extensions/mageia_rpm_gen.py`.
