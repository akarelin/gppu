# Changelog

All notable changes to this project will be documented in this file.

## [2.19.0] - 2025-08-19

### Changed
- Reorganized branch structure:
  - Made ETLs branch content the new master branch
  - Created 3.0 branch from old master with 8-environment merged
  - Renamed ETLs branch to LTS for clarity
  - Deleted main and 122-610-reclassing branches
- Updated version from 2.18.3 to 2.19.0.250819
- Updated README.md with current branch structure and usage

### Added
- gppu added as git submodule to /home/alex/CRAP/gppu

### Removed
- Deleted stale branches: 8-environment (merged), 121-better-base-class-hierarchy (outdated)

### Branch Structure
- **master** (v2.19.0): Production version used by RAN/appdaemon/_adev/Y2
- **3.0** (v3.0.0.26): Modernized refactor with Pydantic and Rich
- **LTS** (v2.18.3): Original stable version preserved as backup

## [2.18.3] - 2025-07-05

### Initial
- Original version extracted from RAN/appdaemon/_adev/Y2