---
name: mageia-update-rpm
description: Update a Mageia RPM to a newer upstream version using mgarepo, spectool, rpmbuild, and Fedora patches.
---

# Mageia RPM Updater

Update an existing Mageia package to a newer upstream version.

## Instructions
* Minimize spec changes when updating packages.
* **Never invoke `rpmbuild` directly — always use `bm`, even for diagnostics.** `bm` builds inside the `<mgarepo>/<package>/` layout and reads the correct `SPECS/`/`SOURCES/`, writing `BUILD/`, `RPMS/`, `SRPMS/` there. A bare `rpmbuild -ba/-bp/-bb` writes to `~/rpmbuild` and looks in `~/rpmbuild/SOURCES`, so it uses the wrong source tree and the wrong output location. To investigate a failure, read the log `SPECS/log.<package>` that `bm` writes, or re-run `bm -p SPECS/<package>.spec` (prep) / `bm -r SPECS/<package>.spec` (prep only) / `bm SPECS/<package>.spec` (full build). Never type `rpmbuild ...` by hand; `bm` calls `rpmbuild` internally, which is fine.
* All checkouts and builds live under a single parent directory named
  `mgarepo`. See "Build location" below.
* Do not change the `sha1.lst` hash file. Leave it untouched even though the `SOURCES/` files no longer match it; a later manual `mgarepo sync` updates it. Do not worry about the mismatch between `SOURCES/` and `sha1.lst` — `bm`/`rpmbuild` do not read `sha1.lst` during builds. (The original instructions wrote `sha1.list`; the actual file is `sha1.lst`.)
* Do not include `-Wl,--allow-shlib-undefined` in LDFLAGS. Use version-independent linking via `%{python3_version}` instead (see step 13).
* The log files may be in another language such as Chinese.
* **Use macros instead of hardcoded strings.** In the spec, any string that varies from version to version — URLs, package names, version numbers, build tags, archive/file names — must be written with macros (`%{version}`, `%{name}`, `%{url}`, `%{built_tag}`, etc.) rather than the literal value. Bump `Version:` and let the macros expand; do not paste `foo-1.2.3` or `.../foo-1.2.3.tar.gz` into `Source:` lines. See "Spec macros" below.

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
  1. `./mgarepo` (current working directory)
  2. `~/mgarepo` (user's home directory)
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

2. **Look online** for a newer version of the package (upstream website, GitHub releases, SourceForge, PyPI, etc.). Determine the new version number and the source file URL.
   Additionally, search for security advisories (CVE, vendor advisories, Mageia security tracker) for the package; collect any relevant security patches and note them for inclusion.

3. **Modify the spec file** (`SPECS/<package>.spec`):
   - If security patches are needed, add `Patch:` lines and `%patch` macros, and adjust `Version:`/`Release:` if needed.
   - Bump `Version:` to the new upstream version.
   - Update `Source0:` (and any other `Source:` lines) to point at the new source file — but write it with macros (`%{version}`, `%{name}`, `%{url}`, `%{built_tag}`) so it tracks `Version:` instead of pasting the new literal string.
   - If the new version is a versioned release (i.e., not a prerelease), set the release counter to 1; otherwise bump `Release:`.
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

9. **Fix dependency errors**:
   If there are errors with missing dependencies, instruct the user to install them by running `urpmi` against the spec file. If the user responds with an error log due to broken dependencies, fix up the dependencies.

10. **Fix errors due to patches**. If the build fails because an old patch no longer applies:
   - Inspect the patch (`Patch01`, etc.) in `SPECS/` or `SOURCES/`.
   - Keep Mageia-related patches and modify them so they apply against the new code (refresh with `diff -u` against the new sources, update context lines, or rebase hunks).
   - Drop a patch only if the fix it provides has already been incorporated upstream in the new version (verify against the upstream source or release notes).
   - Remove or update `Patch:` lines and `%patch` macros accordingly.
   - Re-run `spectool -g` and `bm` until it succeeds.

11. **Do a test build**
   - Once the build requires are satisfied, do a test build with:
     ```bash
     bm SPECS/<package>.spec
     ```
12. **Verify that the build has produced RPMS/SRPMS**

13. **Fix compile issues**
    - If there are any compile issues, create a new patch to fix those issues or modify build instructions in the spec.
    - For Python packages that build C/Cython extensions with the Mavenia hardened `-Wl,--no-undefined` linker flag, add an LDFLAGS export in the spec's `%build` section to link against the Python shared library, so the build does not fail with undefined references to Python C API symbols (e.g. `_Py_NoneStruct`, `PyUnicode_FromString`). A version-independent form is:
      ```spec
      export LDFLAGS="-lpython%{python3_version}"
      ```
      (Place before the Python build macro such as `%pyproject_wheel`.)

14. **Look at the Fedora repo** for recent patches to apply:
    - Check the Fedora dist-git package page (`https://src.fedoraproject.org/rpms/<package>`) for newer patch files and spec changes.
    - Download any relevant patches into `SOURCES/` and add `Patch:` lines plus `%patch` macros to the spec.

15.  **Fix changes to files**
     - If the build fails because of unpackaged files or missing files
       fix the rpm files list to take this into account

## Updating a list of packages

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
- Before a test build, make sure the spec's `BuildRequires:` covers every dependency required by the package's build system: all libraries probed via `./configure` (pkg-config checks, `AC_SEARCH_LIBS`, header checks) and any CMake `find_package` / pkg-config probes must have a matching `BuildRequires:` line. Missing entries are satisfied only by packages already present on the build machine, so the build can succeed there while clean build roots (mock, build daemons) fail or the resulting RPM will not install cleanly — add the missing `BuildRequires:` entries before building.

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
