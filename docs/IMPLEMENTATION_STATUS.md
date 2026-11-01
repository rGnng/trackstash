# Implementation Status

| | |
|---|---|
| **Status** | M0–M6 core implementation complete |
| **Date** | 2026-11-01 |
| **Platform** | macOS 13+, Apple Silicon build |
| **License** | GPL-3.0-only |

## Milestones

| Milestone | Status | Notes |
|---|---|---|
| M0 | Complete | uv/Python 3.12, PySide6 6.11.3, CI, GPL license, docs |
| M1 | Complete | Tracks-compatible UUIDs, mutagen tag engine, Tracks-compatible base schema |
| M2 | Complete | Managed import, quick/full scan, move detection, missing-file handling, search |
| M3 | Complete | Fusion-styled menu-less Qt browser, single-library status, left media editor, responsive Tracks and Albums views, configurable columns, import wizard |
| M4 | Complete | Inline single/multi tag editor with pending changes, auto-numbering, previews, verified writes, artwork, journal, undo/redo |
| M5 | Complete | Template organization, library relocation, UUID remapping, duplicate review, index/Trash deletion |
| M6 | Complete | Backup/restore, settings, ReKey, PyInstaller app bundle, ad-hoc signed DMG |

## Verified behavior

- UUID reference vectors match Tracks/WebTracks, including non-ASCII paths and the
  Swift final-sigma case.
- Metadata round-trips cover FLAC, MP3, M4A, OGG, Opus, WAV, AIFF, and WavPack.
- Bitrates are stored and displayed in Kbps; schema v2 migrates pre-existing values.
- Schema v3 stores track and disc values as text and migrates existing libraries.
- The interface uses Qt Fusion styling, a menu-less action bar, and Settings-hosted library and database management.
- Album artwork is loaded asynchronously from embedded tags for visible albums; there is no cover cache on disk.
- The status bar shows library and selection counts, defaults to visible, and can be disabled in Settings.
- Track and disc values are stored as text, matching tag semantics.
- Window size persists between launches.
- Album grid sorting defaults to date added descending and is configurable in Settings.
- Strong ordering moves files immediately after path-affecting tag edits; mtime preservation is enabled by default.
- Pending artwork paste/add/delete is normalized and written on Save; all existing artwork is replaced or removed.
- Artwork supports Crop to square, Fit to square, and Original aspect ratio modes.
- Spin boxes and combo boxes ignore mouse-wheel changes unless focused.
- The left editor width defaults to 280 px, is user-resizable, and persists between launches.
- Imports copy by default or move on request; sources are untouched in copy mode.
- Import destinations follow the organization template from Settings; per-import tag overrides remain available.
- The import dialog accepts folders or individual files and warns before very large imports.
- Tag edits update files and DB, verify by re-reading, and support undo/redo.
- Organization recomputes song UUIDs from the new relative paths and remaps all
  references in one transaction.
- Quick/full scans discover new files, refresh changed files, and detect external
  moves by content hash.
- Missing files are removed only after explicit selection.
- Exact and probable duplicates are reviewable; deletion is index-only by default.
- The packaged app launches with `--smoke-test`.

Test status at the time of writing:

```text
93 passed, 2 skipped (default suite)
2 passed (real-library integration suite)
```

Real-library integration used a small sample from the Desktop test collection and
one M4A from the external music volume. Only temporary copies were imported and
they were removed afterward.

## Packaging artifacts

```text
dist/TrackStash.app   113 MB
dist/TrackStash.dmg    51 MB
```

The app and DMG are ad-hoc signed. Public distribution still requires a Developer
ID certificate, hardened runtime, notarization, and stapling.

## Known gaps

These are documented rather than silently omitted:

- Filesystem watching, saved views, tag presets, automatic organization, and
  batch transforms are not exposed in the UI.
- Redo covers tag edits, moves, and copy imports; system-Trash deletion is
  irreversible, and redo of move-imports is not supported.
- Artwork supports front-cover embedding/replacement/removal; multiple artwork
  types and sidecar policies are not exposed.
- No online metadata lookup, playback/preview, or playlist import.
- Only an arm64 build is produced; universal2 is a follow-up.
- GitHub Actions CI is configured and has passed for the M6 commits.
