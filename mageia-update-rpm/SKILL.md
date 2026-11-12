---
name: mageia-update-rpm
description: Update a Mageia RPM to a newer upstream version using mgarepo, spectool, rpmbuild, and Fedora patches.
---

# Mageia RPM Updater

Update an existing Mageia package to a newer upstream version.

## Instructions
* Minimize spec changes when updating packages.
* Use `bm` for builds and not `rpmbuild` directly. (`bm` is Mageia's build manager wrapper around rpmbuild.)
* All checkouts and builds live under a single parent directory named
  `mgarepo`. See "Build location" below.
* Do not change sha1.list hash file

## Build location

Everything for one package lives under a single parent directory named `mgarepo`:

```
<mgarepo>/                <- parent directory (created if missing)
  <package>/              <- one subdirectory per package
    SPECS/<package>.spec
    SOURCES/
```

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
- The logs produced by bm are in the SPECS directory.  Please look at
  those to check for errors

## Workflow

If it appears that the instruction has already been performed then skip to the next instruction.

1. **Checkout the build tree**
   - Locate the `mgarepo` parent directory per "Build location" above (check `./mgarepo`, then `~/mgarepo`; create `./mgarepo` if neither exists).
   - `cd` into it and run:
     ```bash
     mgarepo co <package>
     ```
     This creates `mgarepo/<package>/` containing the SPECS/ and SOURCES/ layout from Mageia's package repository.
   - Stop if the package does not exist in the Mageia repository.
   - `cd` into `mgarepo/<package>/`; all following steps assume this working directory.
   - Never run `mgarepo co` from a directory outside the mgarepo parent — it must be run from inside the mgarepo directory itself.

2. **Look online** for a newer version of the package (upstream website, GitHub releases, SourceForge, PyPI, etc.). Determine the new version number and the source file URL.

3. **Modify the spec file** (`SPECS/<package>.spec`):
   - Bump `Version:` to the new upstream version.
   - Update `Source0:` (and any other `Source:` lines) to point at the new source file.
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
   - Drop the patch if the fix is already upstream, or refresh it with `diff -u` against the new sources.
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

14. **Look at the Fedora repo** for recent patches to apply:
    - Check the Fedora dist-git package page (`https://src.fedoraproject.org/rpms/<package>`) for newer patch files and spec changes.
    - Download any relevant patches into `SOURCES/` and add `Patch:` lines plus `%patch` macros to the spec.

## Build Requires

- When creating BuildRequires: prefer `pkgconfig(<package>)` tags over `<package>-devel`.
- Each BuildRequires: should be on a single line.
- Make sure that the BuildRequires is architecture independent (i.e. do not include `lib64<package>`).
- Use `bm` rather than `rpmbuild` for rpm/srpm builds.
- If the spec file contains a `%generate_buildrequires` section (for example one driven by `%pyproject_buildrequires`), the BuildRequires generated by that macro must be inserted into the spec file as explicit `BuildRequires:` lines. Mageia's `urpmi` cannot install dynamically generated build requires, so they have to be written into the spec file explicitly.

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

- It does not upload the new RPM to Mageia's build system (koji).
- It does not create a new package from scratch (use `mageia-rpm-gen` for that).
- It does not choose the "correct" version for you; it reports candidate versions found online and applies the one you (or policy) selects.
