# Implementation Status

| | |
|---|---|
| **Status** | M0–M6 core implementation complete |
| **Date** | 2026-10-31 |
| **Platform** | macOS 13+, Apple Silicon build |
| **License** | GPL-3.0-only |

## Milestones

| Milestone | Status | Notes |
|---|---|---|
| M0 | Complete | uv/Python 3.12, PySide6 6.11.3, CI, GPL license, docs |
| M1 | Complete | Tracks-compatible UUIDs, mutagen tag engine, Tracks-compatible base schema |
| M2 | Complete | Managed import, quick/full scan, move detection, missing-file handling, search |
| M3 | Complete | Qt library browser, track table, detail panel, import wizard |
| M4 | Complete | Single/batch tag editor, previews, verified writes, artwork, journal, undo/redo |
| M5 | Complete | Template organization, UUID remapping, duplicate review, index/Trash deletion |
| M6 | Complete | Backup/restore, settings, ReKey, PyInstaller app bundle, ad-hoc signed DMG |

## Verified behavior

- UUID reference vectors match Tracks/WebTracks, including non-ASCII paths and the
  Swift final-sigma case.
- Metadata round-trips cover FLAC, MP3, M4A, OGG, Opus, WAV, AIFF, and WavPack.
- Imports copy by default or move on request; sources are untouched in copy mode.
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
47 passed, 2 skipped (default suite)
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

- Filesystem watching, library relocation, saved views, tag presets, automatic
  organization, batch transforms, and auto-numbering are not exposed in the UI.
- Redo covers tag edits, moves, and copy imports; system-Trash deletion is
  irreversible, and redo of move-imports is not supported.
- Artwork supports front-cover embedding/replacement/removal; multiple artwork
  types and sidecar policies are not exposed.
- No online metadata lookup, playback/preview, or playlist import.
- Only an arm64 build is produced; universal2 is a follow-up.
- CI is configured but has not been run on a remote runner from this workspace.
