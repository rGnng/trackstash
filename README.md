# TrackStash

TrackStash is a local-first media library manager for people who curate their own
music collections. It imports audio into a managed library, edits embedded tags
safely at scale, organizes files by metadata, and keeps the library index
consistent without cloud dependencies.

> **Status:** M0 scaffold. The application currently opens an empty window. The
> library, import, tagging, and organization workflows are implemented in later
> milestones.

## What is planned

- Managed library imports with copy or move, tag-driven destination paths, and
  duplicate handling.
- Single-track and batch tag editing with previews, verified writes, journaling,
  and undo.
- Embedded and sidecar artwork management.
- Tracks-compatible deterministic UUIDs for libraries, artists, albums, and songs.
- Quick and full library scans with explicit missing-file review.
- Search, filters, saved views, duplicate review, and safe deletion.
- macOS 13+ on Apple Silicon first, with a portable core for later ports.

Not in M0 or v1: online metadata lookup, audio playback or preview, playlist
import. Playlist import is planned after M0.

## Requirements

- macOS 13 or newer
- [uv](https://docs.astral.sh/uv/)
- Python 3.12 (managed by uv)

PySide6 is pinned to **6.11.3** because its macOS wheel targets macOS 13.
PySide6 6.12 and later require macOS 14+.

## Development

```bash
uv python install 3.12
uv sync
uv run trackstash
```

Run the checks:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

The test suite uses Qt's offscreen platform by default.

## Project layout

```text
src/trackstash/
  app.py                 QApplication bootstrap
  __main__.py            console entry point
  core/                  UI-independent domain, storage, and media engine
    compat/              Tracks/WebTracks identity and scan rules
    identity/            UUID generation and remapping
    importing/           managed-library import pipeline
  ui/                    PySide6 widgets
  platform/              macOS-specific services
tests/                   pytest and pytest-qt tests
docs/                    requirements and compatibility documentation
packaging/macos/         release packaging assets
```

## Documentation

- [Requirements](docs/REQUIREMENTS.md)
- [Tracks/WebTracks compatibility](docs/COMPATIBILITY.md)

## License

TrackStash is free software licensed under the
[GNU General Public License v3.0 only](LICENSE). The corresponding source is
published with every binary release. Third-party notices are listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
