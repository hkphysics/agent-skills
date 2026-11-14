---
name: mageia-improve-rpm
description: Improve an existing Mageia RPM by upgrading its source, fixing build issues, and applying patches.
---

# Mageia RPM Improver

Improve an existing Mageia package RPM — bump versions, fix build errors, apply Fedora patches, and ensure clean installs.

## Purpose
This skill is a lighter-weight companion to **mageia-update-rpm**. It focuses on *improving* an already-buildable RPM: checking for stale outputs, verifying public keys, generating vendor sources for Rust packages, and polishing build requires / LDFLAGS so that Python C extensions link against libpython correctly.

## Location

Everything lives under a single parent directory named `mgarepo`:

```
<mgarepo>/                <- parent directory (created if missing)
  <package>/              <- one subdirectory per package
    SPECS/<package>.spec
    SOURCES/
```

**Build location rules** (copied from `mageia-update-rpm/SKILL.md`):

- Search for an existing `mgarepo` parent directory in this order:
  1. `./mgarepo` (current working directory)
  2. `~/mgarepo` (user's home directory)
- If neither exists, create `./mgarepo` in the current directory.
- To check out a package, first `cd` into the `mgarepo` directory, then run `mgarepo co <package>`; the package lands in `<mgarepo>/<package>/`.
- Run `mgarepo co` only from inside the `mgarepo` parent directory — never from a directory that is not the mgarepo parent.
- After checkout, confirm the package files are under `<mgarepo>/<package>/` (with `SPECS/` and `SOURCES/` inside); if they ended up in the current directory instead, move them into the correct `<mgarepo>/<package>/` subdirectory and re-run the checkout.
- Run every step after checkout from inside `<mgarepo>/<package>/`; spec paths below (`SPECS/<package>.spec`) are relative to it.
- The logs produced by bm are in the SPECS directory. Please look at those to check for errors.

## Rules

- **If the build fails because of missing dependencies, stop the build and ask the user to install the deps and then continue with the build.**
- **Never invoke `rpmbuild` directly — always use `bm`, even for diagnostics.** `bm` builds inside `<mgarepo>/<package>/` with the correct `SPECS/`/`SOURCES/`, writing `BUILD/`, `RPMS/`, `SRPMS/` there. A bare `rpmbuild` writes to `~/rpmbuild` and looks in `~/rpmbuild/SOURCES` — the wrong tree. To investigate a failure, read `SPECS/log.<package>` (written by `bm`) or re-run `bm -p SPECS/<package>.spec`; never type `rpmbuild ...` by hand.
- **Use macros instead of hardcoded strings.** In the spec, any string that varies from version to version — URLs, package names, version numbers, build tags, archive/file names — must be written with macros (`%{version}`, `%{name}`, `%{url}`, `%{built_tag}`, etc.) rather than the literal value. Bump `Version:` and let the macros expand; do not paste `foo-1.2.3` or `.../foo-1.2.3.tar.gz` into `Source:` lines. See "Spec macros" below.

### BuildRequires conversion
- When creating or editing `BuildRequires:` lines, prefer `pkgconfig(<package>)` tags over `<package>-devel`.  
- **Any `*-devel` suffix in a BuildRequires entry must be converted to `devel(*)`.** For example:
  - `BuildRequires: <foo>-dev` → `BuildRequires: pkgconfig(<foo>)`
  - `BuildRequires: <foo>-devel` → `BuildRequires: devel(<foo>)` or simply `pkgconfig(<foo>)` as appropriate.
- Each `BuildRequires:` should be on a single line.
- Make sure the BuildRequires is architecture independent (i.e. do not include `lib64<package>`).
- Before a test build, make sure the spec's `BuildRequires:` covers every dependency required by the package's build system: all libraries probed via `./configure` (pkg-config checks, `AC_SEARCH_LIBS`, header checks) and any CMake `find_package` / pkg-config probes must have a matching `BuildRequires:` line. Missing entries are satisfied only by packages already present on the build machine.

### Python checks
- For Python packages, add a `%check` section (or
  equivalent pytest/pytest-run command) which reads
  ```
pushd %{buildroot}%{python3_sitearch}
%pytest <package>
popd
  ```
  to ensure that the tests run in the buildroot environment context
- This ensures that when you update a Python-based Mageia package, the new code passes its own test suite before being packaged.
- When adding Python tests, inspect the test imports and ensure all required packages are included in the BuildRequires section.



## Spec macros

Keep spec lines version-independent so a version bump touches only `Version:`:

- Prefer macros over literals: `%{version}`, `%{name}`, `%{url}` (from a `%global url` or `%global git0`), `%{built_tag}`/`%{shortcommit}` for git checkouts, and existing `%define`/`%global` values.
- A `Source:` should read `%{url}/archive/%{built_tag}/%{name}-%{version}.tar.gz`, not `https://github.com/.../archive/v1.2.3/foo-1.2.3.tar.gz`.
- Define reusable prefixes once (`%global url https://...`, `%global crate foo`, `%define amversion ...`) and reference them, rather than repeating the literal.
- When a pre-existing spec already uses macros, keep that style; do not introduce new hardcoded copies of the same value.
- Hardcoding is acceptable only for values that never track the upstream version (e.g. `Epoch:`), or when no suitable macro exists yet — in which case define one.

## Workflow
- First checkout and build the rpm packages without changes
- Apply the improvements in this skill
- Build it again to see if it builds and fix errors
- If a newer version is used, search for security advisories (CVE, vendor advisories, Mageia security tracker) and include any relevant patches for security issues.

## Usage

Invoke this skill with the package name you want to improve, e.g.:

```bash
# Agent-level: the agent performs every improvement step for package "foo"
mageia-improve-rpm --package foo
```

## Notes
- Always verify the `mgarepo` parent directory before starting.
- Keep `sha1.lst` untouched — a later manual `mgarepo sync` updates it. Do not worry about the mismatch between `SOURCES/` and `sha1.lst` — `bm`/`rpmbuild` do not read `sha1.lst` during builds. (The original instructions wrote `sha1.list`; the actual file is `sha1.lst`.)
- Do not include `-Wl,--allow-shlib-undefined` in LDFLAGS; use version-independent linking via `%{python3_version}`.
