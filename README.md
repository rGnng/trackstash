# TrackStash

TrackStash is a local-first media library manager for people who curate their own
music collections. It imports audio into a managed library, edits embedded tags
safely at scale, organizes files by metadata, and keeps the library index
consistent without cloud dependencies.

![TrackStash library browser](docs/screenshot.png)

> **Status:** M6 implementation. Core managed-library, import, tag editing,
> artwork, organization, duplicate review, deletion, and undo workflows are
> implemented. The app is not yet notarized for public distribution.

## Features

- **Managed library.** One current library at a time, selected from a native
  dropdown. A Library Manager window handles adding, Quick/Full Scan, relocation,
  ReKey, enable/disable, and index removal. Imports copy by default or move on
  request from File → Import…, with a tag-driven destination template.
- **Track context menu.** Edit Tags, Go to Album, Open, Open with, Delete, and
  Show in Finder.
- **Tracks and Albums views.** A sortable track table with movable/resizable
  columns (`Title`, `Format`, `Codec`, `Bitrate` in Kbps, and more) and a
  virtualized album grid with cover art. Double-click an album to filter tracks;
  select multiple albums for batch editing.
- **Configurable columns.** Right-click the track header to show or hide columns,
  auto-fit all widths, or drag sections. Order, width, and visibility persist and
  are also editable in Settings.
- **Tracks-compatible UUIDs.** Library, artist, album, and song IDs use the same
  deterministic MD5 algorithm as the Tracks macOS app and WebTracks.
- **Tag editing.** Edit directly in the left media editor; changed fields are
  highlighted and counted, and Save opens a preview before writing. Multi-track
  selections show shared values and italic `Multiple` placeholders, so one field
  can be applied to the whole selection. Batch edits and per-disc auto-numbering
  are also available from the Edit menu.
- **Artwork.** View, embed, replace, remove, and extract front-cover artwork.
- **Organization.** Rename and move files with a token template, live preview,
  collision detection, UUID remapping, journaling, and undo.
- **Library maintenance.** Quick and full scans, changed-file refresh, missing
  file review, duplicate review, and index-only or system-Trash deletion.
- **Undo and redo.** Journaled tag edits, imports, moves, and index-only
  deletions. Redo is available for tag edits, moves, and copy imports.
- **Local-first.** No online metadata lookup, telemetry, accounts, or cloud
  services. No playback or preview in v1.

## Requirements

- macOS 13 or newer
- [uv](https://docs.astral.sh/uv/)
- Python 3.12 (managed by uv)

PySide6 is pinned to **6.11.3** because its macOS wheel targets macOS 13.
PySide6 6.12 and later require macOS 14+. The v1 bundle is built for Apple
Silicon; a universal2 build for Intel Macs is a follow-up.

## Development

```bash
uv python install 3.12
uv sync
uv run trackstash
```

On first run TrackStash creates `~/Music/TrackStash` and stores its database in
`~/Library/Application Support/TrackStash/library.sqlite`.

When launched with `uv run`, macOS attributes the application menu to the Python
process. Use the packaged `.app` to see the native **TrackStash** application
menu with About, Settings, and Quit.

Useful development flags:

```bash
uv run trackstash --database /tmp/trackstash.sqlite --no-default-library
uv run trackstash --smoke-test
```

Run the checks:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

The test suite uses Qt's offscreen platform by default. Audio fixtures are
generated with `ffmpeg`; tests are skipped when it is unavailable.

### Real-library integration tests

The integration tests are opt-in and never modify the source folders:

```bash
TRACKSTASH_TEST_MUSIC="$HOME/Desktop/emptyAlbums" \
TRACKSTASH_TEST_M4A="/path/to/sample.m4a" \
uv run pytest -m integration
```

Only a handful of files are copied into a temporary library, then removed.

## Packaging

Build an ad-hoc signed macOS app bundle and DMG:

```bash
./packaging/macos/build_dmg.sh
```

Outputs:

- `dist/TrackStash.app`
- `dist/TrackStash.dmg`

The script uses PyInstaller, codesigns the bundle ad-hoc, and creates a
compressed DMG. Public distribution still requires a Developer ID certificate,
notarization, and stapling.

## Project layout

```text
src/trackstash/
  app.py                 QApplication bootstrap and CLI flags
  __main__.py            console entry point
  core/
    identity/            Tracks-compatible UUID generation
    metadata.py          mutagen read/write and canonical tags
    db.py                SQLite schema, upserts, journal, search
    library.py           import, scan, edit, organize, delete, undo
    template.py          tag-driven path templates and sanitization
    artwork.py           album cover cache
    compat/              compatibility notes and future shared helpers
  ui/                    PySide6 window, dialogs, table model
  platform/              platform-specific services
tests/                   pytest and pytest-qt tests
docs/                    requirements and compatibility documentation
packaging/macos/         PyInstaller spec and DMG build script
```

## Known limitations

- No online metadata lookup, audio playback, or preview.
- Playlist import is planned after M0 and is not implemented.
- Filesystem watching, saved views, tag presets, and automatic organization
  are not yet exposed in the UI.
- Redo is supported for tag edits, moves, and copy imports; system-Trash file
  deletion remains irreversible.
- The release DMG is ad-hoc signed, not notarized.

## Documentation

- [Requirements](docs/REQUIREMENTS.md)
- [Tracks/WebTracks compatibility](docs/COMPATIBILITY.md)
- [Implementation status](docs/IMPLEMENTATION_STATUS.md)

## License

TrackStash is free software licensed under the
[GNU General Public License v3.0 only](LICENSE). The corresponding source is
published with every binary release. Third-party notices are listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
