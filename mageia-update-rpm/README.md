# Mageia RPM Updater

`mageia-update-rpm` is a Pi skill that helps Mageia packagers **quality control (QC)**
and update existing RPM packages to newer upstream versions.

The work is split between two parties:

- **The skill (the agent)** does the mechanical, repetitive work — checkout,
  spec edits, source downloads, builds, reading logs, and committing.
- **You (the packager)** make the decisions and do the checks that need a human
  — choose the version, install privileged dependencies, review the diff, and
  sign off on the result.

Each step below is labelled **[skill]** or **[you]** so you know who does what.

## What you need before you start

- A `mgarepo` working area (a parent directory holding one subdirectory per
  package). The skill uses `./mgarepo`, then `~/mgarepo`, and creates
  `./mgarepo` if neither exists.
- Working `mgarepo`, `spectool`, `bm`, and `urpmi` on your machine.

The skill never calls `rpmbuild` directly — always `bm`, which builds inside
your `mgarepo/<package>/` tree.

## Installing the skill

**[you]** Load it in the Pi harness:

```bash
pi --extension ./mageia-update-rpm/index.py
```

---

## Update one package

### 1. Prepare the update — **[skill]** (with your confirmation)

The skill handles the whole preparation pass in one go:
- checks the package out (`mgarepo co <package>`),
- looks upstream (GitHub releases, PyPI, SourceForge, vendor site) and checks
  security advisories (CVE, Mageia security tracker) to propose the new version
  and source URL — **[you]** confirm the version before it is applied,
- edits `SPECS/<package>.spec`: bumps `Version:`, resets `Release:` to 1,
  rewrites `Source:` lines to use macros, and adds `Patch:` lines when security
  patches are needed,
- downloads the new sources (`spectool -g`) into `SOURCES/`,
- runs a test unpack (`bm -r`), reads `SPECS/log.<package>` for errors, and fixes
  the spec if the unpack directory name does not match.

### 2. Install missing build dependencies — **[you]**

When the build reports missing `BuildRequires:`, **[you]** install them with
`urpmi`. The skill will not run `sudo urpmi` for you. It can list exactly which
packages are missing (mapped from the tags) and, if you prefer, prepare the
command for you to approve.

### 3. Fix and build — **[skill]**

The skill refreshes or drops patches that no longer apply, then runs the full
build (`bm SPECS/<package>.spec`), fixing compile issues (new patch or spec
tweak) and rebuilding until RPMs are produced in `RPMS/` and `SRPMS/`.

### 4. QC the result — **[you]**

Review the outcome before anything is committed:
- The build succeeded and RPMs were produced.
- The file list picked up new/removed files (no unpackaged or missing files).
- The version and release are what you intended.
- Any upstream changelog notes worth mentioning are captured.

### 5. Sync, commit, and submit — **[you]**
The skill does NOT run this; it runs `sync_commit.py` for you. You execute it:

```bash
cd /home/joe/bench/git/agent-skills/mageia-update-rpm
./sync_commit.py <package> <package> ...   # specific packages
./sync_commit.py --all                     # all packages with built RPMs
./sync_commit.py --file packages.txt       # one package per line
./sync_commit.py --all --dry-run           # preview first
```

For each package it shows the `svn diff` and asks you to approve:
- No local changes → it skips sync/commit and goes straight to the submit
  offer.
- Changes present → it asks **[you]** whether to sync + commit.
- If the package is already on `pkgsubmit.mageia.org`, it will not ask you to
  submit again.
- When it asks whether to run `mgarepo submit`, the default answer is **no**.

A summary of committed / submitted / skipped / errors prints at the end.

---

## Update many packages (batch workflow)

The skill works in batches of 10–20 so that all missing dependencies are found
before anyone builds. For each package in a batch, it runs `mgarepo co`, bumps
`Version:`, downloads sources via `spectool -g`, and runs prep only (`bm -l -p
SPECS/<package>.spec`); it also collects any missing
`BuildRequires:` from `SPECS/log.<package>`. **[you]** installs those dependencies
with `urpmi`; then the skill re-runs the build after deps are installed.

### Batch flow (per package)
- **[skill]** `mgarepo co`, bump Version, `spectool -g`, `bm -l -p SPECS/<package>.spec`
- **[skill]** collect missing BuildRequires from log
- **[you]** install them with `urpmi` (mapped via `urpmq --what-provides <tag>`)
- **[skill]** re-run `bm -l SPECS/<package>.spec` once deps are present

---

## Install buildrequires with `instbr.py` — **[skill prepares, you approve]**

To resolve and install every build dependency for one or more packages:

```bash
./instbr.py                              # every package under mgarepo/
./instbr.py <package> <package>          # specific packages
./instbr.py --dry-run                    # plan only, do not install
```

The skill covers both explicit `BuildRequires:` lines and the implicit
dependencies emitted at build time (e.g. `pkgconfig(...)`, `python3dist(...)`),
skips what is already installed, then installs the rest with `sudo urpmi`. The
actual install needs root/sudo, so **[you]** authorize it.

---

## Sample prompts (pulling data from check.mageia.org)

The skill works well when you ask it to pull current status from
`check.mageia.org` and `pkgsubmit.mageia.org` before you decide what to do:

### Is this package already submitted?

```
Check https://pkgsubmit.mageia.org/?q=<package> and tell me whether <package>
is already submitted there. If it is, don't offer to run `mgarepo submit` again.
```

### Which packages need updating?

```
Query https://check.mageia.org for Mageia mga11 packages whose shipped version
is behind upstream. List the top 10 by download count that have a newer release
available, with: package name, current Mageia version, upstream version, and
source URL.
```

### Are there security advisories?

```
Check https://check.mageia.org and the Mageia security tracker for open CVEs or
security advisories affecting <package>. If there are, list the advisory IDs and
affected versions before I bump it.
```

### Plan a security-first batch

```
Fetch the mga11 packages with pending security updates from
https://check.mageia.org. For each, compare the spec Version: against the
sha1.lst committed version to see if it was already bumped locally. Write a
packages.txt ordered by severity (security first, then download count), ready for
./sync_commit.py --file packages.txt.
```

### Check a build before committing

```
For <package> under mgarepo/, confirm RPMS/*.rpm and SRPMS/*.rpm both exist.
Then run ./sync_commit.py <package> --dry-run and report what it would do.
```

---

## Files

- `SKILL.md` — the agent's step-by-step instructions for this workflow.
- `index.py` — single-package update driver.
- `sync_commit.py` — sync, commit, and submit helper.
- `instbr.py` — buildrequire resolution and install helper.
