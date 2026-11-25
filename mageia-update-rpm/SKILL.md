---
name: mageia-update-rpm
description: Update a Mageia RPM to a newer upstream version using mgarepo, spectool, rpmbuild, and Fedora patches.
---

# Mageia RPM Updater

Update an existing Mageia package to a newer upstream version.

## Instructions
* **Note: The terminal shell may not be bash (e.g. it could be zsh), so invoke bash scripts explicitly under bash, e.g. `bash script.sh` or `#!/usr/bin/env bash`.
* Minimize spec changes when updating packages.
* **Never invoke `rpmbuild` directly — always use `bm`, even for diagnostics.** `bm` builds inside the `<mgarepo>/<package>/` layout and reads the correct `SPECS/`/`SOURCES/`, writing `BUILD/`, `RPMS/`, `SRPMS/` there. A bare `rpmbuild -ba/-bp/-bb` writes to `~/rpmbuild` and looks in `~/rpmbuild/SOURCES`, so it uses the wrong source tree and the wrong output location. To investigate a failure, read the log `SPECS/log.<package>` that `bm` writes, or re-run `bm -p SPECS/<package>.spec` (prep) / `bm -r SPECS/<package>.spec` (prep only) / `bm SPECS/<package>.spec` (full build). Never type `rpmbuild ...` by hand; `bm` calls `rpmbuild` internally, which is fine.
* The `bm` output goes to a log file in the `SPECS/` directory (e.g. `SPECS/log.<package>`); its stdout and stderr will be mostly blank, so read the log file to check for errors.
* **Do not scan the entire filesystem to locate files or dependencies.** All lookups must be scoped to the package's `mgarepo` checkout directory (`<mgarepo>/<package>/`) and use the toolchain-provided commands (`urpmi`, `urpmq`, `rpm -q`, etc.). Wide filesystem searches are a sign of misconfiguration and will be rejected.
* **Before looking into the source code of tools and running tests to determine behavior, do a web search for documentation first.** Consult the official Mageia/rpm/packaging docs, the tool's man page, or a web search — only fall back to code inspection when documentation does not resolve the question.
* All checkouts and builds live under a single parent directory named
  `mgarepo`. See "Build location" below.
* Do not change the `sha1.lst` hash file. Leave it untouched even though the `SOURCES/` files no longer match it; a later manual `mgarepo sync` updates it. Do not worry about the mismatch between `SOURCES/` and `sha1.lst` — `bm`/`rpmbuild` do not read `sha1.lst` during builds. (The original instructions wrote `sha1.list`; the actual file is `sha1.lst`.)
* Do not include `-Wl,--allow-shlib-undefined` in LDFLAGS. Use version-independent linking via `%{python3_version}` instead (see step 14).
* The log files may be in another language such as Chinese.
* **Use macros instead of hardcoded strings.** In the spec, any string that varies from version to version — URLs, package names, version numbers, build tags, archive/file names — must be written with macros (`%{version}`, `%{name}`, `%{url}`, `%{built_tag}`, etc.) rather than the literal value. Bump `Version:` and let the macros expand; do not paste `foo-1.2.3` or `.../foo-1.2.3.tar.gz` into `Source:` lines. See "Spec macros" below.
* **Never hardcode `/usr/lib64` or `/usr/lib`** — use the `%{_libdir}` macro instead (e.g. `/usr/lib64` on x86_64, `/usr/lib` on ARM). Avoid hardcoding any part of a filename when a macro is available; use `%{name}`, `%{version}`, etc.
* **Do not list `.debug` files in `%files`.** Debug info is automatically extracted and packaged by `find-debuginfo` into the `-debuginfo` (or `-debugsource`) subpackage. Manually listing a `.debug` path duplicates the file into both the main and the debuginfo package, and breaks on architectures whose `%{_libdir}` differs from x86_64 (e.g. ARM uses `/usr/lib`, not `/usr/lib64`) with a `File not found` error. Never add entries like `/usr/lib/debug/%{_libdir}/lib%{name}.so.*.debug` to `%files`; let the debuginfo machinery handle it.
* **Do not use bare directories in `%files`.** Never hardcode `/usr/share/pkgconfig/`, `/usr/share/cmake/`, `/usr/share/gtk-doc/`, or any other absolute directory path in the spec. Always use macro-based paths that expand correctly per-architecture and distro: `%{_datadir}/pkgconfig/%{name}.pc`, `%{_datadir}/cmake/%{name}/`, `%{_datadir}/gtk-doc/html/%{name}/`, etc. Bare paths like `/usr/share/pkgconfig/foo.pc` work on x86_64 but break on ARM (where `/usr/lib` is used instead of `/usr/lib64`) and fail `check-files`.
* **Do not remove functionality to get a spec to build** Do not remove
  features to get a spec to build (i.e. %check) 

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
	
Rules:
- Search for an existing `mgarepo` parent directory in this order:
  `./mgarepo` (current working directory)
- If neither exists, create `./mgarepo` in the current directory.
- Do not search deeper than these two paths; if the user keeps `mgarepo` elsewhere, ask them for its location instead of guessing.
- To check out a package, first `cd` into the `mgarepo` directory, then run `mgarepo co <package>`; the package lands in `<mgarepo>/<package>/`.
- Run `mgarepo co` only from inside the `mgarepo` parent directory — never from a directory that is not the mgarepo parent.
- After checkout, confirm the package files are under `<mgarepo>/<package>/` (with `SPECS/` and `SOURCES/` inside); if they ended up in the current directory instead, move them into the correct `<mgarepo>/<package>/` subdirectory and re-run the checkout.
- Run every step after checkout from inside `<mgarepo>/<package>/`; spec paths below (`SPECS/<package>.spec`) are relative to it.
- The logs produced by bm are in the SPECS directory.  Please look at those to check for errors

## Workflow

If it appears that the instruction has already been performed then skip to the next instruction.

1. **Checkout the build tree**
   - Locate the `mgarepo` parent directory per "Build location" above (check `./mgarepo`, then `~/mgarepo`; create `./mgarepo` if neither exists).
   - `cd` into it and run:
     ```bash
     mgarepo co <package>
     ```
	 Do not check out build trees outside of mgarepo

2. **Look online** for a newer version of the package (upstream website, GitHub releases, SourceForge, PyPI, etc.). Determine the new version number and the source file URL.
   Additionally, search for security advisories (CVE, vendor advisories, Mageia security tracker) for the package; collect any relevant security patches and note them for inclusion.

3. **Modify the spec file** (`SPECS/<package>.spec`):
   - If security patches are needed, add `Patch:` lines and `%patch` macros, and adjust `Version:`/`Release:` if needed.
   - Bump `Version:` to the new upstream version.
   - Update `Source0:` (and any other `Source:` lines) to point at the new source file — but write it with macros (`%{version}`, `%{name}`, `%{url}`, `%{built_tag}`) so it tracks `Version:` instead of pasting the new literal string.
   - **When the version is bumped up, reset the release to 1** (`Release: %mkrel 1`); do not keep a stale or incremented release counter.
   - Note: `%mkrel` is a valid Mageia macro (it expands to `<release>.mga11`); use it for the `Release:` tag (e.g. `Release: %mkrel 1`).

4. **For Rust packages, redo the vendor package.**
   If the spec uses `%cargo_prep`, `%{crates_source}`, or `cargo_generate_buildrequires`, the crate dependencies are vendored and must be regenerated for the new version:
   ```bash
   # Extract the crate name from the spec: %global crate <name>
   rust2rpm -t mageia -V auto <crate> -o <tmpdir>
   # Copy the vendor tarball (<crate>-<version>-vendor.tar.xz) and any regenerated patches into SOURCES/, and the new spec over SPECS/<package>.spec
   ```
   `rust2rpm -V auto` resolves the latest compatible dependency set and produces a vendor tarball containing all vendored crate sources, so the build runs fully offline. The crate name comes from the `%global crate` line, not the `rust-` prefixed package name.

5. **For Go packages, apply the Go-specific build fixes.**
   Go builds fail in three predictable ways that are easy to miss:

   - **The Go module path may have changed.** The import path comes from `go.mod`, not the GitHub URL. If a release moved the module (e.g. buildah `github.com/containers/buildah` → `go.podman.io/buildah`), update the spec's `import_path` and the GOPATH symlink in `%build` to the new module path even though the download URL (`git0`/`Source:`) still points at GitHub. Check the new `go.mod` first.
   - **`go build` chokes on VCS stamping in a mixed git+svn tree.** The `bm`/`mgarepo` tree is SVN; `%autosetup -Sgit` leaves an inner `.git`. A `go build` invoked by the spec's `Makefile` (module mode) then dies with `error obtaining VCS status: multiple VCS detected: git ... and svn`. Fix by exporting `GOFLAGS=-buildvcs=false` in the affected `%build`/`%install` section (and/or `rm -rf .git` in `%prep` after `%autosetup`).
   - **The Go module cache is read-only and blocks cleanup.** A previous/failed build leaves `_build/pkg/mod/...` files at mode `r-x` (read-only), so `rm -rf` of the build dir fails with `operation not permitted`. Run `chmod -R u+w BUILD` before removing it.

6. **Download the updated sources** into `SOURCES/`:
   ```bash
   spectool -g SPECS/<package>.spec
   ```
   `spectool` reads the `Source:` URLs from the spec and fetches them.
   Note: `spectool -g` writes downloaded files into the current working
   directory; move them into `SOURCES/` for a proper build.
   For Rust packages this step downloads the `.crate` file if the vendor tarball wasn't already present from step 4.

7. **Do an test unpack**:
   ```bash
   bm -r SPECS/<package>.spec   # or -bb for binary only
   ```
   
8. **Fix unpacking errors**
   - If the unpack creates an error look in BUILD to see if the unpack
     directory matches and modify the SPEC if it does not
   - When handling issues with unpacking sources, consult the online docs
     for rpm specs before running tests to determine behavior.

9. **Fix dependency errors**:
   If there are errors with missing dependencies, instruct the user to install them by running `urpmi` against the spec file. If the user responds with an error log due to broken dependencies, fix up the dependencies.

10. **Audit CMake dependencies against `BuildRequires:`** (mandatory for CMake-based packages, before the test build)
   A successful local build proves nothing: CMake's `find_*` calls will happily locate libraries that happen to be installed on this machine but are not declared in the spec. The build then succeeds here and breaks on clean buildroots (mock, build daemons) or on remote machines. Verify coverage by reading the CMake files, not by observing that the build worked.
   - In the unpacked source (`BUILD/<package>-<version>` after `bm -r`, or the pristine tarball), list every dependency probe:
     ```bash
     grep -rniE 'find_package[[:space:]]*\(|pkg_check_modules|pkg_search_module|find_library|find_path|find_program|FetchContent_Declare|ExternalProject_Add' \
       --include=CMakeLists.txt --include='*.cmake' .
     ```
   - For each probe, find the Mageia package that provides it:
     ```bash
     urpmq --what-provides pkgconfig(foo)   # preferred
     urpmq --what-provides 'cmake(Foo)'     # some CMake config files are provided under cmake(Foo) tags
     ```
   - Every dependency that is probed and used by the build must have a matching `BuildRequires:` line in the spec (prefer `pkgconfig(...)` tags per the Build Requires section). For `find_package(Foo COMPONENTS A B)`, each required component needs its own `BuildRequires:`.
   - Optional probes (a `find_package` without `REQUIRED`, or `find_library` used under `if(...)`) must not be silently picked up from the build host: either add the `BuildRequires:` and let the feature be enabled, or disable the auto-detection explicitly (e.g. `-DFOO_ENABLED=OFF` / `-DWITH_FOO=OFF` passed to cmake in `%build`) so the package behaves identically on every machine. Never let whether the dependency is used depend on what happens to be installed locally.
   - Watch for `FetchContent_Declare` / `ExternalProject_Add` / "if(NOT FOO_FOUND) ... use bundled copy" fallbacks: these silently download or build a bundled copy when the system library is missing. Replace the fallback with a hard requirement — add the `BuildRequires:` and make the probe mandatory (or remove/disable the bundled fallback) so the build fails loudly instead of diverging between machines.
   - Add the missing `BuildRequires:` lines, then re-check: every `find_package`/`pkg_check_modules`/`find_library` hit from the grep above must trace to a `BuildRequires:` line in the spec. Only then proceed to the test build. If `bm` still succeeds locally, that is not evidence — the grep-to-spec cross-check is.

11. **Fix errors due to patches**. If the build fails because an old patch no longer applies:
   - Inspect the patch (`Patch01`, etc.) in `SPECS/` or `SOURCES/`.
   - Keep Mageia-related patches and modify them so they apply against the new code (refresh with `diff -u` against the new sources, update context lines, or rebase hunks).
   - Drop a patch only if the fix it provides has already been incorporated upstream in the new version (verify against the upstream source or release notes).
   - Remove or update `Patch:` lines and `%patch` macros accordingly.
   - Re-run `spectool -g` and `bm` until it succeeds.

12. **Do a test build**
   - Once the build requires are satisfied, do a test build with:
     ```bash
     bm SPECS/<package>.spec
     ```
13. **Verify that the build has produced RPMS/SRPMS**

14. **Fix compile issues**
    - If there are any compile issues, create a new patch to fix those issues or modify build instructions in the spec.
    - For Python packages that build C/Cython extensions with the Mageia hardened `-Wl,--no-undefined` linker flag, add an LDFLAGS export in the spec's `%build` section to link against the Python shared library, so the build does not fail with undefined references to Python C API symbols (e.g. `_Py_NoneStruct`, `PyUnicode_FromString`). A version-independent form is:
      ```spec
      export LDFLAGS="-lpython%{python3_version}"
      ```
      (Place before the Python build macro such as
      `%pyproject_wheel`.)  Insert this string if you get an compile
      error due to lack of python symbols
	  

15. **Look at the Fedora repo** for recent patches to apply:
    - Check the Fedora dist-git package page (`https://src.fedoraproject.org/rpms/<package>`) for newer patch files and spec changes.
    - Download any relevant patches into `SOURCES/` and add `Patch:` lines plus `%patch` macros to the spec.

16.  **Fix changes to files**
     - If the build fails because of unpackaged files or missing files
       fix the rpm files list to take this into account

## Updating a list of packages — Batch Pipeline Method

When asked to update a list of packages (rpms), use a **batch pipeline** to maximize throughput.

### Pipeline Overview

```
Discovery → User Deps → Build → Next Batch
```

1. **Discovery (batch of 10–20 packages)**
   - For each package in the batch, run `mgarepo co <package>` from inside the `mgarepo` parent directory.
   - Bump `Version:` in `SPECS/<package>.spec`.
   - Download sources with `spectool -g SPECS/<package>.spec`, then move any downloaded tarballs/files into `SOURCES/`.
   - Run the prep stage only: `bm -l -p SPECS/<package>.spec`
   - **Record which dependencies are missing** (from the bm log in `SPECS/log.<package>` or from the prep step's `BuildRequires` failures).
   - **Do not build yet** — the goal is fast discovery of dependency gaps across the whole batch.
   - **Web search before source inspection.** Before diving into the source code of tools, build systems, or the package itself to determine behavior (e.g. how a macro works, how a build system probes dependencies, whether a feature is on by default), do a web search for documentation first — consult the official Mageia/rpm/packaging docs, the tool's man page, or upstream docs. Only fall back to code inspection when documentation does not resolve the question.

2. **Dependency install (user action)**
   - Report the missing `BuildRequires:` per package to the user and ask them to install the packages with `urpmi`.
   - Do **not** use `sudo urpmi ...` yourself — ask the user to install them.
   - Map each `python3dist()` tag or pkg-config tag to the actual Mageia package name with `urpmq --what-provides <tag>` so the user gets the right package to install.

3. **Build pass (same batch)**
   - After the user reports the deps installed, re-run each package with `bm -l SPECS/<package>.spec`.
   - If a build-only problem appears, fix the spec and retry. Packages are not done until the full build succeeds and RPMs are produced.

4. **Next batch**
   - While the user installs deps for batch N, run discovery for batch N+1.
   - This overlap keeps throughput high.

5. **Ordering / skipping rules**
   - If a package cannot be checked out (missing from repo), skip it.
   - If prep fails for reasons unrelated to deps (upstream patch breakage, source 404, upstream code bug), note it and skip it — don’t block the batch.
   - If a build fails only because a missing dep wasn’t actually provided by the installed RPM (wrong `Provides` version — e.g. `python3dist(mypy) = 1.15` vs spec’s `>= 2`), skip it and point out which dep must be rebuilt.

### Batch Report Format

After each batch, post a compact report like:

```
## Batch N Report
✅ Built: pkg-a 1.2.3, pkg-b 0.4.0
🔧 Needs deps: pkg-c (urpmi python3-xyz), pkg-d (urpmi lib64abc-devel)
❌ Skip: pkg-e (source 404), pkg-f (upstream patch broken)
📂 Next batch: pkg-g, pkg-h, ...
```

### Batch Size

Each batch should be about **10–20 packages**. Smaller batches waste time; larger batches make dependency-discovery reports unwieldy and risk letting too many slices sit idle.

## Batch build script (build_rpms.py)

For automated batch building of Python packages the repository ships `build_rpms.py`.  It is a helper that operates on the `python_no_maintainer.csv` CSV (generated by `python3dist` lookup) and supports three modes:

* `build_rpms.py` or `build_rpms.py N` — build the first **N** packages from the CSV (default 20).  After the batch finishes, `--background` can launch the next N packages asynchronously.
* `build_rpms.py --all` — build **every** package in the CSV in a single run; no background chaining is needed since all packages are processed at once.
* `build_rpms.py --packages pkg1 pkg2 ...` — build only the named packages listed; packages not found in the CSV are reported and skipped.

The script accepts additional options:

* `--csv PATH` — alternative CSV file (default: `MAGEIA_CSV` env, `/tmp/python_no_maintainer.csv`).
* `--log PATH` — log file to append results to (default: `MAGEIA_LOG` env, `/tmp/pipe_results.tsv`).
* `--root DIR` — mgarepo root directory (default: `MAGEIA_ROOT` env, `.`).
* `--background` — (N mode only) after finishing, launch the next N packages in the background.

See the script's own `--help` output for the full usage and examples.

## Updating a list of packages (legacy single-pass mode)

When asked to update a list of packages (rpms), process them one at a time, in this order:

1. Check out the package (`mgarepo co <package>`) and update the
   version and release in the spec (steps 2–3 of the workflow).
2. make sure that all of the sources are updated in the SOURCES
   directory using spectool
3. Attempt the prep stage only, to verify the new sources unpack and `%prep` applies:
   ```bash
   bm -p SPECS/<package>.spec
   ```
4. If prep fails because dependencies are missing, do not stop the whole run:
   - Inform the user which dependencies the package needs (from the bm log in SPECS/) and that it is being skipped.
   - Skip that package and move on to the next one in the list.
5. **Build every package that passed prep with `bm SPECS/<package>.spec`** and report success or failure per package. **Note: a package is not fully updated until it has been built with the new version.**

The skill will attempt to build all packages it can, skipping only those with missing build dependencies.

### Batch Pipeline Example (real-world)

Batch 1 discovery (10 packages):
1. All python packages prepped fine.
2. Build failures revealed: `python3dist(setuptools-scm)` unsatisfied, `python3dist(flit-core)` missing for some, etc.
3. User ran `urpmi` for the listed Mageia packages.
4. Re-build pass produced 7 successful RPMs; 2 failed only due to wrong Provides metadata in dep RPMs, 1 needed its %check disabled.

This method catches all missing deps in one sweep instead of one at a time while each package builds.

## Spec macros

Keep spec lines version-independent so a version bump touches only `Version:`:

- Prefer macros over literals: `%{version}`, `%{name}`, `%{url}` (from a `%global url` or `%global git0`), `%{built_tag}`/`%{shortcommit}` for git checkouts, and existing `%define`/`%global` values.
- A `Source:` should read `%{url}/archive/%{built_tag}/%{name}-%{version}.tar.gz`, not `https://github.com/.../archive/v1.2.3/foo-1.2.3.tar.gz`.
- Define reusable prefixes once (`%global url https://...`, `%global crate foo`, `%define amversion ...`) and reference them, rather than repeating the literal.
- When a pre-existing spec already uses macros, keep that style; do not introduce new hardcoded copies of the same value.
- Hardcoding is acceptable only for values that never track the upstream version (e.g. `Epoch:`), or when no suitable macro exists yet — in which case define one.

## Build Requires

- When creating BuildRequires: prefer `pkgconfig(<package>)` tags over `<package>-devel`.
- Each BuildRequires: should be on a single line.
- Make sure that the BuildRequires is architecture independent (i.e. do not include `lib64<package>`).
- Use `bm` rather than `rpmbuild` for rpm/srpm builds. Never run `rpmbuild` directly (see the build rule above): it uses `~/rpmbuild` instead of the package tree.
- If the spec file contains a `%generate_buildrequires` section (for example one driven by `%pyproject_buildrequires`), the BuildRequires generated by that macro must be inserted into the spec file as explicit `BuildRequires:` lines. Mageia's `urpmi` cannot install dynamically generated build requires, so they have to be written into the spec file explicitly.
- Before a test build, make sure the spec's `BuildRequires:` covers every dependency required by the package's build system: all libraries probed via `./configure` (pkg-config checks, `AC_SEARCH_LIBS`, header checks) and any CMake `find_package` / pkg-config probes must have a matching `BuildRequires:` line. Missing entries are satisfied only by packages already present on the build machine, so the build can succeed there while clean build roots (mock, build daemons) fail or the resulting RPM will not install cleanly — add the missing `BuildRequires:` entries before building. For CMake-based packages this is a mandatory, explicit audit (see workflow step 10): grep the unpacked source for `find_package` / `pkg_check_modules` / `find_library` / `FetchContent_Declare` and trace every hit to a `BuildRequires:` line. Local build success is not evidence of coverage.
- **Ensure all necessary dependencies are listed.** The spec must contain a `BuildRequires:` entry for every dependency the build actually needs. After any build failure or when a new upstream version introduces new dependencies, inspect `SPECS/log.<package>` (or the build log) and add the missing `BuildRequires:` lines before declaring the package updated.
- **Remove BuildRequires that are unused or already included via another BuildRequires.** A BuildRequires that no part of the build consumes is dead weight and must be removed: no `dependency()`/`pkg_check_modules`/`find_package`/`find_library` probe in the build files (meson.build, CMakeLists.txt, *.pc probing in build scripts, autotools configure.ac), no `.pc` reference from kept entries' Requires, no use in `%build`/`%install`/`%check`, and no `%cmake`/`%meson` fallback that needs it. A BuildRequires whose provider package is already guaranteed to be installed by another kept BuildRequires is redundant and must be removed — e.g. `pkgconfig(gio-2.0)`, `pkgconfig(gio-unix-2.0)` and `pkgconfig(girepository-2.0)` all ship in libglib2.0-devel (kept via `pkgconfig(glib-2.0)`); all muffin `pkgconfig(muffin-*)` files ship in libmuffin-devel (kept via `pkgconfig(libmuffin-0)`); gtk+-3.0-devel Requires atk-bridge-2.0, cairo-xlib, x11, xcomposite, xext and xfixes, so those come with `pkgconfig(gtk+-3.0)`. Verify with `urpmf <file-or-.pc>` and `rpm -qR <provider-devel>` (or `rpm -q --requires <provider-devel>`), never by assumption, and only via hard `Requires:` — not `Recommends:`/`Suggests:`. Do not remove a BuildRequires that supplies something the build needs but no kept BuildRequires guarantees (e.g. `gobject-introspection` provides g-ir-scanner, required by `gnome.generate_gir`, and is not pulled in by lib64girepository-devel in current cauldron — keep it even though it has no `.pc` probe). When in doubt, keep the entry. After pruning, rebuild with `bm` to confirm the spec still builds.

## Usage

Invoke this skill with the package name you want to update, for example:

```bash
# Agent-level: the agent runs the full workflow for package "foo"
mageia-update-rpm --package foo
```

The agent performs every step above and reports the result (built RPM, applied patches, or remaining errors).

## Dependencies

- `mgarepo`, `spectool`, `rpmbuild`, `rpm`, `wget`/`curl`, `git`, `bm`
- `rust2rpm` (for Rust packages, step 4)
- Network access to the upstream project and Fedora dist-git

## Search
- Prefer using `urpmq` to find the list of packages.
- Use `urpmq --provides <package>` to find the tags which can be used to include the package in a BuildRequires.
 
## What it does not do

It does not upload the new RPM to Mageia's build system (koji).
It does not create a new package from scratch (use `mageia-rpm-gen` for that).
It does not choose the "correct" version for you; it reports candidate versions found online and applies the one you (or policy) selects.
It does not delete successful build information - successful RPM builds are preserved, but intermediate build state can be cleaned up after verification.

## Handling Build Failure Categories

The build failure taxonomy maps directly to the four package categories defined under **Package Categorization**:

| Category | Dominant failure types | Response |
|---|---|---|
| **Successfully built** | none — build completed, RPM produced | Record result; move on |
| **All deps installed (ready to build)** | *Missing source / 404*, *Missing build dep*, *Patch fails*, *Unpack error* | Read `SPECS/log.<pkg>` for exact error; fix per table below; re-run full `bm SPECS/<package>.spec`. |
| **Done & uploaded** | none — already uploaded | Skip; do not re-attempt. |
| **Not started** | *Any* — package never checked out or attempted | Run `mgarepo co <package>`, bump spec, `spectool`, then `bm -l -p` prep-only test first. |

### Per-failure-type responses

| Failure type | Symptoms | Response |
|---|---|---|
| **Missing source / 404** | `Failed to download`, 0-byte tarball, `Cannot read ... No such file` | Clean SOURCES, fix source URL (macros), verify upstream, fetch manually |
| **Missing build dep** | `BuildRequires: ... is missing`, or `%generate_buildrequires` can't install via urpmi | Do NOT build yet; collect all missing deps, ask user, map tags via `urpmq --what-provides` |
| **Patch fails to apply** | `1 out of 1 hunk FAILED`, `.rej` files | Inspect upstream; drop patch if fix upstream, else refresh hunk via `diff -u` |
| **Unpack error** | `cd: <dir>: No such file or directory` | Check tarball name vs `%setup -n`; fix extracted dir name |
| **Missing / untracked files** | `check-files` finds installed-but-unpackaged files | Fix `%files` section; do NOT add debug files |
| **BuildRequires provides mismatch** | Build runs locally but dep version wrong | Skip; point out which dep needs rebuilding |
| **Source version unavailable** | GitHub tags/API 404, PyPI missing version | Skip; note upstream availability |
| **Build env / env-var** | LDFLAGS mismatch, offline vendor failure | Adjust spec env/vars (macro), not source |

**General response rules:**
- Batch skip (source 404 / broken patch / unavailable version) → skip, don't block batch
- Batch build fails → collect missing deps for remaining packages before asking user
- Never block batch on a single package; record failure type and move on
- After fix, re-run `bm` full build (not just prep) and read log
