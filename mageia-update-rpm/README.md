# Mageia RPM Updater

A skill for updating Mageia RPM packages to newer upstream versions.

## Overview

This skill provides a workflow for updating existing Mageia packages to newer
upstream versions. It uses `mgarepo` to checkout the build tree, searches online
for newer versions, updates the spec file, downloads sources with `spectool`,
builds the RPM, and applies patches from the Fedora dist-git repository.

## Workflow

1. **Checkout** the package build tree with `mgarepo co <package>`
2. **Search online** for a newer version of the package
3. **Update the spec file** with the new version and source URL
4. **Download sources** with `spectool -g`
5. **Build the RPM** with `rpmbuild -ba`
6. **Fix patch errors** by refreshing or dropping patches
7. **Apply Fedora patches** from the dist-git repository

## Usage

```bash
# Run the skill for a specific package
python mageia-update-rpm/index.py --package <name>
```

## Dependencies

- `mgarepo`, `spectool`, `rpmbuild`, `rpm`, `wget`/`curl`, `git`
- Network access to upstream project and Fedora dist-git

## Files

- `SKILL.md` - Skill instructions and workflow
- `index.py` - Main script implementing the workflow
- `README.md` - This file