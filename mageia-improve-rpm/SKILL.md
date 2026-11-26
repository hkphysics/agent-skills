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
- **Convert `*-devel` suffix in a BuildRequires entry should to
  pkgconfig() or develop() style tags with the appropriate package name
  - Each `BuildRequires:` should be on a single line.
- Make sure the BuildRequires is architecture independent (i.e. do not include `lib64<package>`).
- Before a test build, make sure the spec's `BuildRequires:` covers every dependency required by the package's build system: all libraries probed via `./configure` (pkg-config checks, `AC_SEARCH_LIBS`, header checks) and any CMake `find_package` / pkg-config probes must have a matching `BuildRequires:` line. Missing entries are satisfied only by packages already present on the build machine.

### BuildRequires pruning
- **Remove BuildRequires that are unused or already included via another BuildRequires.** A BuildRequires that no part of the build consumes is dead weight and must be removed: no `dependency()`/`pkg_check_modules`/`find_package`/`find_library` probe in the build files (meson.build, CMakeLists.txt, *.pc probing in build scripts, autotools configure.ac), no `.pc` reference from kept entries' Requires, no use in `%build`/`%install`/`%check`, and no `%cmake`/`%meson` fallback that needs it. A BuildRequires whose provider package is already guaranteed to be installed by another kept BuildRequires is redundant and must be removed — e.g. `pkgconfig(gio-2.0)`, `pkgconfig(gio-unix-2.0)` and `pkgconfig(girepository-2.0)` all ship in libglib2.0-devel (kept via `pkgconfig(glib-2.0)`); all muffin `pkgconfig(muffin-*)` files ship in libmuffin-devel (kept via `pkgconfig(libmuffin-0)`); gtk+-3.0-devel Requires atk-bridge-2.0, cairo-xlib, x11, xcomposite, xext and xfixes, so those come with `pkgconfig(gtk+-3.0)`. Verify with `urpmf <file-or-.pc>` and `rpm -qR <provider-devel>` (or `rpm -q --requires <provider-devel>`), never by assumption, and only via hard `Requires:` — not `Recommends:`/`Suggests:`. Do not remove a BuildRequires that supplies something the build needs but no kept BuildRequires guarantees (e.g. `gobject-introspection` provides g-ir-scanner, required by `gnome.generate_gir`, and is not pulled in by lib64girepository-devel in current cauldron — keep it even though it has no `.pc` probe). When in doubt, keep the entry. After pruning, rebuild with `bm` to confirm the spec still builds.

### Python dependency tags
- Prefer `python3dist(<dist-name>)` over `python3-<package>` in `BuildRequires:` (and in explicit `Requires:`) for Python library dependencies, e.g. `BuildRequires: python3dist(requests)` instead of `BuildRequires: python3-requests`.
  - Mageia's `python3-rpm-generators` auto-generates `python3dist(<distname>)` provides from the upstream dist name (PEP 503-normalized), so the tag resolves regardless of what the providing RPM is actually named (`python3-foo`, `python-foo`, bundled subpackages, etc.).
  - Dist name, not import name and not RPM name: use `python3dist(pyyaml)`, not `python3dist(yaml)` and not `python3-pyyaml`.
  - This matches Mageia policy ("Automatically-generated dependencies take the form python3dist(modname)") and Fedora's Python packaging guidelines, which Mageia follows.
- Do NOT convert non-library Python packages to `python3dist()`: keep `python3-devel`, `python3-rpm-macros`, the interpreter (`python3`), and tools like `python3-pytest`/`python3-setuptools` when the spec needs those specific RPMs. When in doubt, check what the RPM actually provides (`rpm -q --provides python3-foo`) before converting.
- Explicit `Requires:` on Python modules in `%files` packages are usually redundant — rpmbuild auto-generates them as `python3dist()`. But do not drop them blindly: build first, then check `rpm -qRp <built.rpm> | grep python3dist`. Drop only the ones that appear; some packages (e.g. cinnamon, whose Python is driven from JS/C) get none from the generators and must keep the explicit tags.

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

## Spec Section Guidelines

- **Use standard macros over hardcoded paths:** Reference `%{buildroot}`, `%{_bindir}`, `%{_sysconfdir}`, `%{_mandir}`, and `%{_unitdir}` so packages stay portable across architectures and RHEL releases.
- **Prefer %global over %define:** Use `%global` for spec-level macros so they evaluate consistently rather than re-evaluating lazily in nested contexts.
- **Keep sections focused:**
  - `%prep`: Unpack sources and apply patches.
  - `%build`: Compile or prepare artifacts (use language build macros like `%py3_build` or `%make_build`).
  - `%install`: Stage files strictly under `%{buildroot}`.
  - `%check`: Run unit or smoke tests during the build when possible.
  - `%files`: Explicitly list owned files and directories, marking config files with `%config(noreplace)` and docs with `%doc` so upgrades do not clobber local changes.

## Spec File Macros & Sections

- Use %autosetup instead of %setup: Unpacks sources and applies declared patches automatically in %prep.
- Use %{buildroot} instead of $RPM_BUILD_ROOT: Keeps variable syntax consistent across the spec file.
- Use standard directory macros: Prefer %{_bindir}, %{_libdir}, %{_datadir}, %{_sysconfdir}, and %{_unitdir} instead of /usr/bin or /etc.
- Use %make_build and %make_install: Replaces manual make %{?_smp_mflags} and make install DESTDIR=%{buildroot} commands.
- Omit %clean and rm -rf %{buildroot} in %install: Modern RPM handles buildroot cleanup automatically.
- Use Requires(pre) / Requires(post): Explicitly declare dependencies needed only during specific scriptlet phases.
- Use %systemd_post, %systemd_preun, and %systemd_postun_with_restart: Standardize service management rather than calling systemctl directly.
- Use %ldconfig_scriptlets or automatic triggers: Avoid manual /sbin/ldconfig calls in %post and %postun on modern distributions.
- Use Recommends: and Suggests: (Weak Dependencies): Prefer weak dependencies for optional add-ons instead of forcing hard Requires:.

## Security & Build Flags

- Use %set_build_flags (or default %build flags): Ensures compiler hardening flags (CFLAGS, CXXFLAGS, LDFLAGS) are properly exported.
- Avoid AutoReqProv: no: Let RPM's automatic dependency generator track shared libraries and interpreters unless fixing a specific packaging bug.
- Use %license instead of %doc for license files: Installs license files into the dedicated licensedir for compliance tracking.

## Quick Comparison: Modern vs. Legacy

| Packaging Task    | Preferred (Modern)    | Avoid (Legacy) |
|-------------------|------------------------|----------------|
| Unpacking & Patching    | %autosetup -p1    | %setup -q + %patch0 -p1 |
| Compiling    | %make_build    | make %{?_smp_mflags} |
| Installing    | %make_install    | make install DESTDIR=$RPM_BUILD_ROOT |
| License Files    | %license LICENSE    | %doc LICENSE |
| System Paths    | %{_bindir}/app    | /usr/bin/app |

## Workflow
- First checkout and build the rpm packages without changes
- Apply the improvements in this skill
- Build it again to see if it builds and fix errors
- Run `rpmlint <package>.spec` against the spec and address any problems found (warnings, errors).
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
- Do not include `-Wl,--allow-shlib-undefined` in LDFLAGS, and **never add an `export LDFLAGS` that links against Python (`-lpython`)** in a Python package.
