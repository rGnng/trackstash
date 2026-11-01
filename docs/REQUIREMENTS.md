# TrackStash — Requirements Specification

| | |
|---|---|
| **Status** | Approved — M0–M6 core implementation delivered |
| **Date** | 2026-10-31 |
| **Product** | TrackStash |
| **Document language** | English (project-wide convention) |

---

## 1. Overview

TrackStash is a local-first media library manager for people who curate their own
music collections. It scans media folders, builds a searchable index, edits
embedded metadata safely at scale, and reorganizes files into a consistent
library structure.

The name reflects the core promise: a trustworthy stash of tracks whose metadata
and file layout are always under the user's control.

### 1.1 Problem statement

Existing tag editors are either single-file tools, overloaded with features, or
unsafe for large batch operations. Collectors need a tool that can:

- index a large library without re-reading every file on each launch;
- import external files into a managed library and organize them by their tags;
- apply tag changes to hundreds of tracks with a clear preview and a reliable undo;
- enforce a consistent folder and filename structure;
- work entirely offline, with no cloud dependency or vendor lock-in.

### 1.2 Product principles

1. **Local-first.** All data lives on the user's machine. No telemetry and no
   network access by default.
2. **Safety before speed.** Every destructive operation is previewed, journaled,
   and reversible.
3. **Format-aware.** Unknown tags and embedded artwork are preserved unless the
   user explicitly changes them.
4. **Fast at scale.** The application remains responsive with six-figure track
   counts.
5. **English only in v1.** The UI, documentation, code comments, commit messages,
   and error messages are written in English. Metadata content may use any
   Unicode script.
6. **Open source.** The application is distributed under GPL-3.0-only, and the
   corresponding source is published with every binary release.

---

## 2. Goals and non-goals

### 2.1 Goals for v1

- **G-1** Scan one or more library roots and maintain an incremental index.
- **G-2** Read, edit, and write embedded tags for the core audio formats.
- **G-3** Support batch editing with preview, progress, cancellation, and undo.
- **G-4** Manage embedded and sidecar artwork.
- **G-5** Rename and move files using user-defined templates, with collision
  detection and undo.
- **G-6** Provide fast search, filtering, and saved views.
- **G-7** Detect exact and probable duplicates without ever deleting automatically.
- **G-8** Keep the core engine independent of the UI so that a CLI and future
  Windows/Linux frontends can reuse it.
- **G-9** Import external files into a managed library by copy or move, organized
  by tag-driven path templates.
- **G-10** Generate core UUIDs with the Tracks/WebTracks deterministic algorithm
  and keep references consistent when paths change.
- **G-11** Remove tracks from the index or move their files to the macOS Trash,
  with explicit confirmation and honest undo semantics.

### 2.2 Non-goals for v1

- **NG-1** Audio playback and preview.
- **NG-2** Streaming, cloud sync, or multi-user collaboration.
- **NG-3** Mobile or web-hosted editions.
- **NG-4** Online metadata lookup of any kind (MusicBrainz, Discogs, AcoustID, or
  other services).
- **NG-5** DRM-protected content.
- **NG-6** Video container tagging.
- **NG-7** Podcast or audiobook-specific workflows.
- **NG-8** A command-line interface. The core will be CLI-ready, but the CLI ships
  after v1.
- **NG-9** CUE sheet parsing, splitting, or gapless album handling.
- **NG-10** Audio transcoding or format conversion.
- **NG-11** CD ripping.
- **NG-12** Playlist creation and management in v1. Playlist import is a separate
  later feature (Section 5.12).
- **NG-13** Importing or migrating an existing Tracks/WebTracks database.
- **NG-14** Referencing arbitrary external folders in place without importing
  them into a managed library.

---

## 3. Target users and key scenarios

### 3.1 Personas

- **The collector** — 5,000–100,000 tracks across multiple drives; cares about
  consistent album artist, artwork, and folder structure.
- **The DJ** — needs accurate BPM, key, genre, and fast filtering; edits in bulk.
- **The archivist** — values provenance, reversibility, and preservation of
  unknown metadata.

### 3.2 Key scenarios

- **S-1 First run.** The user adds a library root, scans it, and reviews the
  results. Files with parse errors are reported without stopping the scan.
- **S-2 Album cleanup.** The user filters to one album, fixes album artist, year,
  genre, and cover art for all tracks in one batch, previews the diff, and saves.
- **S-3 Large batch edit.** The user selects 800 tracks, sets a comment, clears a
  custom field, and renumbers tracks per disc; the operation is previewed and can
  be undone as a single unit.
- **S-4 Reorganization.** The user applies the template
  `{album_artist}/{year} - {album}/{disc}-{track:02} {title}` to a selection,
  reviews collisions, and executes the move.
- **S-5 Duplicate review.** The user compares two copies of the same album by
  bitrate, format, and tags, keeps the better one, and removes the other from the
  index or moves it to the macOS Trash.
- **S-6 Managed import.** The user imports an album folder from Downloads. The
  wizard reads tags, previews the destination paths, copies the files into the
  library, optionally writes edited fields, and indexes them with stable UUIDs.
  The source folder remains untouched.
- **S-7 Move and rekey.** The user corrects an album artist and applies the
  organization template. Files move, song UUIDs are recomputed from the new
  relative paths, and all references are remapped in one transaction.
- **S-8 Delete.** The user removes a track from the index, or explicitly chooses
  to move its file to the macOS Trash. The dialog states which outcome is
  reversible and which is not.

---

## 4. Scope and assumptions

- **A-1** Audio files are the only supported media type in v1. Video is out of
  scope (D-01).
- **A-2** The product is a native desktop application with a local database.
- **A-3** The application is single-user and runs on one machine at a time.
- **A-4** Library roots may reside on external or network drives. An unavailable
  root must not cause data loss or automatic removal of its tracks.
- **A-5** The database is a cache and an index. Embedded file tags remain the
  source of truth.
- **A-6** The application is written in Python 3.12+ with PySide6 (Qt 6 Widgets).
  Mutagen provides embedded tag I/O. Swift/AppKit is ruled out because it would
  force a rewrite for the planned Windows/Linux ports.
- **A-7** macOS is the only v1 target and the only development platform, but all
  non-UI code must remain portable; platform-specific code is isolated behind
  interfaces.
- **A-8** Original application code is licensed under GPL-3.0-only. PySide6 is
  used under GPLv3 and mutagen under GPL-2.0-or-later; no dependency incompatible
  with GPLv3 may be introduced.
- **A-9** All project artifacts are written in English.
- **A-10** TrackStash manages its own library roots. Imports copy by default or
  move on request from an external source into a selected root, and destination
  paths are derived from tags.
- **A-11** Core entity IDs follow the Tracks/WebTracks deterministic UUID
  algorithm. Auxiliary records use random UUIDv4 values.
- **A-12** TrackStash creates new databases only. It does not open, migrate, or
  write a Tracks/WebTracks `library.sqlite`.
- **A-13** Tracks/WebTracks implementation methods may be ported for
  compatibility, but TrackStash has no runtime dependency on either project.

---

## 5. Functional requirements

Requirement keywords follow RFC 2119: **MUST**, **SHOULD**, **MAY**.
Priorities: **P0** = required for v1, **P1** = expected for v1, **P2** = later.

### 5.1 Library management

| ID | Priority | Requirement |
|---|---|---|
| LIB-01 | P0 | The user MUST be able to add, rename, disable, and remove library roots. Removing a library MUST only remove its index entries and MUST NOT delete files. |
| LIB-02 | P0 | The application MUST scan library roots recursively. |
| LIB-03 | P0 | Scans MUST be incremental, using path, size, and modification time to skip unchanged files. A full rescan MUST be available. |
| LIB-04 | P0 | The scanner MUST classify files as added, changed, unchanged, moved, or missing. Moves SHOULD be detected by content hash when path and size heuristics are inconclusive. |
| LIB-05 | P0 | Scan progress MUST show the current file, processed count, and error count, and MUST be cancellable. |
| LIB-06 | P0 | Files that cannot be parsed MUST be recorded with an error state; the scan MUST continue. |
| LIB-07 | P1 | Users MUST be able to define ignore globs and hidden-directory policy per library. |
| LIB-08 | P1 | An optional filesystem watcher SHOULD keep the index current after scans. |
| LIB-09 | P1 | When a root is unavailable, its tracks MUST be marked *offline*, not deleted. |
| LIB-10 | P2 | The user MAY rescan only the current selection or a single folder. |
| LIB-11 | P1 | The user SHOULD be able to relocate a library root and remap its file paths and UUIDs without losing tags, views, or history. |
| LIB-12 | P0 | Managed library roots MUST be the only destinations for imports. The application MUST NOT present an external folder as a live library without importing it. |
| LIB-13 | P0 | The scanner MUST skip hidden files and directories, MUST NOT follow directory symlinks, and MUST canonicalize both library roots and file paths. |
| LIB-14 | P0 | When library roots overlap, the deepest enabled root MUST own a file; the same file MUST NOT be indexed twice. |
| LIB-15 | P0 | Quick Scan MUST discover new paths only. Full Scan MUST also re-read files whose size or modification time changed. |

### 5.2 Metadata extraction

| ID | Priority | Requirement |
|---|---|---|
| META-01 | P0 | The reader MUST extract format, duration, bitrate, sample rate, channels, bit depth where applicable, file size, and modification time. |
| META-02 | P0 | The reader MUST map format-specific tags into a canonical field set (Section 7.2). |
| META-03 | P0 | Unknown and custom tags MUST be preserved on read and displayed read-only. Multi-value fields MUST retain all values. If a format cannot round-trip an unknown field, the editor MUST warn before writing. |
| META-04 | P0 | The reader MUST detect embedded artwork, including MIME type, dimensions, and checksum. |
| META-05 | P1 | The reader SHOULD expose lyrics and sort fields when present. |
| META-06 | P0 | Tag parsing MUST never modify a file. |
| META-07 | P0 | Indexed metadata MUST be cached in the database and refreshable on demand. |

### 5.3 Tag editing

| ID | Priority | Requirement |
|---|---|---|
| TAG-01 | P0 | The user MUST be able to edit all canonical fields for a single track. |
| TAG-02 | P0 | The user MUST be able to edit a multi-track selection. Each field has three states: *unchanged*, *set to value*, or *clear*. |
| TAG-03 | P0 | The editor MUST show which fields are mixed across the selection and allow keeping or overwriting them. |
| TAG-04 | P0 | Saving MUST present a diff preview of affected files and fields before writing. |
| TAG-05 | P0 | Tag writes MUST preserve the audio stream and all untouched tags, including unknown fields, where the format supports it. When preservation is not possible, the preview MUST warn and require explicit confirmation. |
| TAG-06 | P0 | A tag write MUST be verified by re-reading the file after saving. Failures MUST be reported per file. |
| TAG-07 | P0 | Every write operation MUST be journaled and undoable as a unit (see SAFE-01). |
| TAG-08 | P1 | The user SHOULD be able to copy tags from one track and paste selected fields onto others. |
| TAG-09 | P1 | The application SHOULD provide auto-numbering for track and disc fields within a selection. |
| TAG-10 | P1 | The application SHOULD provide text transforms: trim whitespace, collapse spaces, title case, find/replace, and regular-expression replace. |
| TAG-11 | P1 | The user SHOULD be able to save and apply tag presets. |
| TAG-12 | P1 | Input validation MUST reject invalid track numbers, dates, and BPM values before writing. |
| TAG-13 | P1 | The user MUST be able to revert unsaved edits to on-disk values. |
| TAG-14 | P1 | The ID3 write version (v2.3 or v2.4) SHOULD be configurable. |
| TAG-15 | P2 | Advanced users MAY strip tag frames or remove all tags, behind an explicit confirmation. |
| TAG-16 | P1 | Read-only files, locked files, and insufficient permissions MUST be detected before a batch write and reported in the preview. |
| TAG-17 | P0 | If a file changed on disk since it was indexed, the write MUST detect the change, warn, and re-read the current tags before applying the edit. |
| TAG-18 | P1 | Tag writes SHOULD use a temporary file and atomic rename where the container allows; otherwise a full-file backup MUST be created before writing. |

### 5.4 Artwork

| ID | Priority | Requirement |
|---|---|---|
| ART-01 | P0 | The user MUST be able to view and extract embedded artwork. |
| ART-02 | P0 | The user MUST be able to add, replace, and remove front-cover artwork for a selection. |
| ART-03 | P1 | Multiple artwork types (front, back, booklet, artist) SHOULD be manageable where the format supports them. |
| ART-04 | P1 | The application SHOULD support assigning a folder image to all tracks in that folder. |
| ART-05 | P1 | The application MUST NOT create a disk cover cache; artwork is read from embedded tags on demand for visible albums and cached only in memory. |
| ART-06 | P1 | Duplicate artwork SHOULD be detected by checksum. |
| ART-07 | P1 | `cover.jpg`/`folder.jpg` sidecar files SHOULD be discoverable, with a per-library policy for embedding. |

### 5.5 File organization

| ID | Priority | Requirement |
|---|---|---|
| ORG-01 | P0 | The user MUST be able to rename and move files with a token-based template (Section 7.3). |
| ORG-02 | P0 | A live preview MUST show every source and destination path before execution, including any song UUID that will change. |
| ORG-03 | P0 | Paths MUST be sanitized for the host OS, including reserved names, illegal characters, and length limits. |
| ORG-04 | P0 | Collisions MUST be detected and resolved by skip, auto-suffix, or an explicitly confirmed overwrite. Detection MUST be case-insensitive on case-insensitive filesystems. Silent overwrite is forbidden. |
| ORG-05 | P0 | A dry-run mode MUST be available for every organization operation. |
| ORG-06 | P0 | Moves MUST be journaled and undoable. When a move changes a song's library-relative path, its UUID MUST be recomputed and every reference MUST be remapped in the same transaction. |
| ORG-07 | P1 | The user SHOULD be able to copy instead of move, and to move tracks between libraries. |
| ORG-08 | P1 | Empty source folders SHOULD be removed only when the user enables that option. |
| ORG-09 | P2 | An inbox workflow MAY import new files into the library and apply a template in one step. |
| ORG-10 | P0 | The application MUST refuse to move files outside configured library roots unless the user explicitly confirms. |
| ORG-11 | P1 | Automatic organization MAY be enabled per library. When enabled, tag edits that change the destination MUST include the move, ID remap, and undo in the same preview and operation; when disabled, organization is a separate action. |

### 5.6 Search, browsing, and views

| ID | Priority | Requirement |
|---|---|---|
| VIEW-01 | P0 | The main window MUST provide a track table with configurable, sortable columns. |
| VIEW-02 | P0 | Search MUST cover title, artist, album artist, album, genre, comment, and path. |
| VIEW-03 | P0 | Common filters MUST include format, bitrate range, missing artwork, missing required tags, and duplicates. |
| VIEW-04 | P0 | The table MUST be virtualized and remain responsive with 100,000 rows. |
| VIEW-05 | P1 | Tracks SHOULD be groupable by album and album artist. |
| VIEW-06 | P1 | Saved views and smart collections SHOULD persist filter and sort definitions. |
| VIEW-07 | P1 | A detail panel SHOULD show technical properties, file path, and raw tags. |
| VIEW-08 | P1 | The user SHOULD be able to reveal a file in Finder/Explorer/file manager. |
| VIEW-09 | P2 | A short audio preview MAY be added after v1; no playback or preview is implemented in v1. |

### 5.7 Duplicates and integrity

| ID | Priority | Requirement |
|---|---|---|
| DUP-01 | P1 | Exact duplicates MUST be detectable by content hash (size + partial hash + full hash). |
| DUP-02 | P1 | Probable duplicates SHOULD be detectable by album artist, title, album, and duration proximity. |
| DUP-03 | P1 | A comparison view MUST show tags, format, bitrate, and artwork side by side. |
| DUP-04 | P1 | The application MUST NOT delete files automatically. Removal means moving files to the macOS Trash with confirmation, or removing them from the index only. |
| DUP-05 | P1 | Missing files MUST be listed and relinkable by search. |
| DUP-06 | P1 | Unsupported and corrupt files MUST be reportable from a diagnostics view. |

### 5.8 History and safety

| ID | Priority | Requirement |
|---|---|---|
| SAFE-01 | P0 | Every write operation MUST create a journal entry containing the prior tag state (including artwork) and the prior path for each affected file. |
| SAFE-02 | P0 | The last *N* reversible operations (configurable retention, default 50) MUST be undoable, and undo/redo history MUST survive application restarts. Redo MUST be available for undone operations until a new edit occurs. |
| SAFE-03 | P0 | If the application crashes mid-operation, the next launch MUST detect the incomplete journal and offer recovery or rollback. |
| SAFE-04 | P0 | Batch operations MUST support cancellation. Files already completed remain journaled and undoable. |
| SAFE-05 | P0 | Full-file backups MUST be optional per operation; tag snapshots are always stored. |
| SAFE-06 | P0 | The application MUST make no network requests by default. |
| SAFE-07 | P1 | Undo MUST verify that target files still match the journaled state; if a file changed or is missing, the operation MUST stop and report the conflict. |
| SAFE-08 | P0 | Index-only deletions MUST be undoable. File deletions moved to the system Trash MUST be labeled irreversible inside the application. |
| SAFE-09 | P0 | Every UUID remap MUST record enough prior state in the operation journal (path, names, namespace) to audit and reverse it. No long-term alias table or old-ID index is retained. |

### 5.9 Command-line interface (post-v1)

The CLI is deferred until after the desktop release. The core engine and database
layer must remain free of UI dependencies so the CLI can be added without
refactoring. Priorities below are relative to the post-v1 phase.

| ID | Priority | Requirement |
|---|---|---|
| CLI-01 | P2 | `trackstash scan`, `list`, `show`, `tag set`, `organize`, `duplicates`, and `doctor` commands SHOULD be available. |
| CLI-02 | P2 | Machine-readable output MUST be available as JSON. |
| CLI-03 | P2 | The CLI MUST use distinct exit codes for success, usage error, partial failure, and fatal error. |
| CLI-04 | P2 | Destructive commands MUST require `--dry-run` or `--yes` semantics; dry-run is the default. |
| CLI-05 | P2 | A configuration file MAY supply library roots and defaults. |

### 5.10 Settings and application data

| ID | Priority | Requirement |
|---|---|---|
| SET-01 | P0 | Settings MUST cover database location, backup retention, default ID3 version, import template defaults, album grid sorting, automatic organization, and default deletion behavior. |
| SET-02 | P1 | The database MUST be backed up and restorable from the application. |
| SET-03 | P1 | The user SHOULD be able to export and import settings. |
| SET-04 | P1 | A diagnostics bundle (logs, versions, database statistics; no personal metadata) SHOULD be exportable. |
| SET-05 | P1 | Light, dark, and system themes SHOULD be supported. |
| SET-06 | P1 | Common actions SHOULD have keyboard shortcuts. |

### 5.11 Import, update, and deletion

#### Import

| ID | Priority | Requirement |
|---|---|---|
| IMP-01 | P0 | The user MUST be able to import files and folders from outside a library into a selected managed library. |
| IMP-02 | P0 | Copy MUST be the default import mode and MUST leave the source untouched. Move MUST be available as an explicit option. |
| IMP-03 | P0 | The importer MUST read tags before planning destinations and MUST show an editable field set in the import wizard. |
| IMP-04 | P0 | Only fields explicitly edited by the user are written to the imported file, after it reaches its destination. Untouched tags MUST be preserved. |
| IMP-05 | P0 | Destination paths MUST be derived from a configurable tag template, with a live per-file preview. |
| IMP-06 | P0 | Collisions and duplicates MUST be detected before copying. The user chooses skip, keep both, or replace; silent overwrite is forbidden. Replace MUST back up the existing destination first. |
| IMP-07 | P0 | Import MUST be journaled and cancellable. Undo removes files copied by the operation and restores files moved by it. |
| IMP-08 | P0 | After copy or move and optional tag writing, the importer MUST index the file with a Tracks-compatible UUID derived from its final library-relative path. |
| IMP-09 | P1 | Imports MUST report per-file progress and errors, and MUST leave the source untouched when a file fails before the copy commits. |
| IMP-10 | P0 | The importer MUST NOT follow symlinks that escape the selected source or the target library root. |
| IMP-11 | P1 | When tags are missing, the destination preview MAY fall back to filename or folder values, but tags MUST NOT be written unless the user edits them. |
| IMP-12 | P1 | Importing a folder tree SHOULD preserve album and disc grouping and reuse a single cover where available. |
| IMP-13 | P2 | A watch folder MAY import new files automatically with the same preview and safety rules. |
| IMP-14 | P1 | Files already inside the target library root MUST be indexed in place rather than copied; files from another managed root follow the cross-library copy/move rules. |

#### Update and rescan

| ID | Priority | Requirement |
|---|---|---|
| UPD-01 | P0 | Quick Scan MUST discover new files in managed roots. Full Scan MUST also refresh files whose size or modification time changed. |
| UPD-02 | P0 | Upserts MUST update base fields while preserving `date_added`, play counts, stars, and other user metadata. |
| UPD-03 | P0 | A path change MUST be treated as a move when the content hash matches a known missing file; the song UUID MUST be recomputed from the new path and all references remapped. |
| UPD-04 | P0 | Tag edits MUST update file tags and the database in one journaled operation, with re-read verification. |
| UPD-05 | P0 | Organization after tag edits MUST move the file, rewrite the path, recompute IDs, and remap references in the same transaction. |
| UPD-06 | P0 | If a file changed on disk since indexing, the update MUST warn and re-read the current tags before overwriting them. |
| UPD-07 | P0 | Missing files MUST be reviewed; only explicitly selected rows are removed, and a scan MUST NOT delete files. |
| UPD-08 | P0 | Batch updates MUST be cancellable; completed files remain journaled and undoable. |
| UPD-09 | P1 | ReKey MUST recompute the namespace and all core IDs, remap references, and back up the database before writing. |
| UPD-10 | P1 | When an artist or album identity changes into an existing row, the rows MUST merge deterministically: the existing row wins, songs are reassigned, and orphan albums, artists, and `ts_artwork` rows are cleaned up. |

#### Deletion

| ID | Priority | Requirement |
|---|---|---|
| DEL-01 | P0 | Deleting a track from the library removes its index rows by default; the file remains on disk. |
| DEL-02 | P0 | The user MAY choose to move the file to the macOS Trash as part of deletion; this requires a separate explicit confirmation. |
| DEL-03 | P0 | File deletion via the system Trash is NOT undoable within the application and the confirmation MUST state this. Index-only deletion MUST be undoable. |
| DEL-04 | P0 | The deletion preview MUST list affected tracks, file sizes, and whether files will be trashed. |
| DEL-05 | P0 | Deleting a library MUST remove only its index rows; files are never touched. |
| DEL-06 | P1 | Orphan albums, artists, and `ts_artwork` rows SHOULD be cleaned up after index deletion. |
| DEL-07 | P1 | Deleting a track MUST update or remove references in the same transaction. |
| DEL-08 | P2 | A bulk removal of missing files MAY be offered after a Full Scan, with the same preview and confirmation rules. |

### 5.12 Post-M0: playlist import

Playlist import is planned after M0 and is explicitly excluded from the M0
scaffold. Its milestone placement is to be decided later. It is documented here
so the data model and ID rules leave room for it.

| ID | Priority | Requirement |
|---|---|---|
| PLI-01 | P2 | The user SHOULD be able to import M3U, M3U8, PLS, and other common playlist formats. |
| PLI-02 | P2 | Entries SHOULD resolve by absolute path, library-relative path, or a Tracks UUID URL; unresolved and ambiguous entries MUST be reported. |
| PLI-03 | P2 | A preview MUST show matched, missing, and ambiguous entries before a playlist is created or updated. |
| PLI-04 | P2 | Import MUST preserve entry order, handle BOM/encoding variants, and apply an explicit duplicate policy. |
| PLI-05 | P2 | Imported playlists MUST be stored in `ts_playlists` and `ts_playlist_items` added by a later migration. |
| PLI-06 | P2 | Re-importing the same playlist SHOULD update it without creating duplicate entries or duplicate playlists. |
| PLI-07 | P2 | Source playlist files MUST never be modified by the importer. |

---

## 6. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-01 | **Performance:** an initial scan of 10,000 local files SHOULD complete within 3 minutes on an SSD; cached browsing and search SHOULD respond within 100 ms at p95 for 100,000 tracks. |
| NFR-02 | **Scale:** the design target is 200,000 tracks per library and 500,000 tracks overall. |
| NFR-03 | **Reliability:** a crash or power loss MUST NOT corrupt the database or leave files half-written. Writes must be atomic where the platform allows. |
| NFR-04 | **Platforms:** macOS 13+ is P0 and the only v1 target; PySide6 is pinned to 6.11.3, whose wheels target macOS 13. PySide6 6.12+ targets macOS 14+, so it cannot be used while macOS 13 support is required. Apple Silicon (arm64) is the primary architecture; a universal2 build for Intel Macs is a P1 release goal. Windows 11 and Linux (Ubuntu 22.04+) are P2 porting targets. |
| NFR-05 | **Privacy:** no telemetry, analytics, or automatic update checks in v1. |
| NFR-06 | **Accessibility:** full keyboard navigation, visible focus, and WCAG 2.1 AA contrast. |
| NFR-07 | **Unicode:** metadata and filenames MUST support arbitrary Unicode, including normalization differences on macOS. |
| NFR-08 | **Security:** path handling MUST prevent traversal outside library roots; templates MUST NOT permit command execution. |
| NFR-09 | **Maintainability:** the core engine MUST be covered by unit and integration tests using fixture files. CI MUST run `ruff`, `mypy`, and `pytest`, and builds MUST be reproducible from a clean checkout with pinned dependencies via `uv.lock`. |
| NFR-10 | **Observability:** structured, rotating logs and a user-visible operation history. |
| NFR-11 | **Packaging:** PyInstaller one-folder `.app` and a signed, notarized macOS DMG for v1; Windows and Linux packages follow with the ports. |
| NFR-12 | **Portability:** the core MUST NOT import PySide6 or depend on AppKit or macOS-only APIs. Platform services (file reveal, trash, paths, watchers) are accessed through interfaces, with implementations under `src/trackstash/platform/`. |
| NFR-13 | **Licensing:** original code is GPL-3.0-only. PySide6 is used under GPLv3 and mutagen under GPL-2.0-or-later. The corresponding source, dependency notices, and license texts MUST be published with every binary release. |
| NFR-14 | **Compatibility:** core UUIDs MUST match reference vectors generated by Tracks/WebTracks, including Unicode and Swift-compatible lowercasing. Base-table upserts MUST be validated against fixture databases. |
| NFR-15 | **Integrity:** ID remaps, imports, moves, tag writes, and deletions MUST be transactional and journaled. A failure MUST leave either the prior state or a recoverable journal entry. |

---

## 7. Data model and canonical fields

### 7.1 Core entities

TrackStash uses its own SQLite database. Library tables follow the Tracks column
layout where practical; TrackStash-specific data lives in `ts_*` tables. A
Tracks/WebTracks database is never opened or migrated (A-12).

Tracks-compatible base tables:

- **libraries** — id, path, kind, name, identifier, id_namespace, date_added, enabled.
- **artists** — id, name.
- **albums** — id, title, artist_id, genre, year, artwork (always `NULL`; no disk cover cache).
- **songs** — id, path, library_id, title, artist_id, album_id, genre, year, track, track_total, disc, disc_total, comments, duration, date_added, play_count, rating, loved, last_played, skip_count, mtime, file_size. Track and disc fields use TEXT affinity because tags are text.

TrackStash extension tables:

- **ts_song_tags** — one row per song for scalar fields absent from `songs`: album_artist, composer, lyricist, isrc, bpm, musical_key, compilation, lyrics, sort fields, MusicBrainz IDs, label, catalog number, barcode, release country, media, script, language, conductor, orchestra, ensemble, work, movement, movement number, original date, and ReplayGain values.
- **ts_audio_properties** — song id, format, codec, bitrate, sample rate, channels, bit depth, and lossless flag.
- **ts_file_state** — song id, content hash, hash state, last scan time, scan error, and offline flag.
- **ts_tag_value** — song id, field key, position, value; multi-value fields and unknown/custom tags.
- **ts_artwork** — song id, artwork type, MIME type, dimensions, and checksum; per-track embedded artwork metadata. Artwork is not cached on disk; `cache_path` is a legacy unused column.
- **ts_operations** / **ts_operation_items** — journal; prior state includes tags, artwork, path, names, and namespace needed to reverse a remap.
- **ts_track_fts** — FTS5 index over searchable text.
- **ts_saved_views**, **ts_presets**, **ts_settings** — user configuration.

Artwork is read from embedded tags on demand for visible albums and cached only
in memory for the current session; `albums.artwork` remains `NULL` for Tracks
compatibility. No cover files are written to disk.

`songs.id` is the primary key and changes when the library-relative path
changes. `libraries.path` and `songs.path` are canonical and unique. The operation
journal records the prior path, names, and namespace needed to reverse a remap,
and all extension-table references are updated in the same transaction. Old IDs
are not retained after the journal entry is pruned.

### 7.2 Canonical tag fields

Title, artists (multi-value), album artist, album, track number, track total,
disc number, disc total, year, original date, genre (multi-value), composer,
lyricist, comment, lyrics, ISRC, BPM, musical key, compilation flag, sort title,
sort artist, sort album artist, sort album, MusicBrainz recording/release/artist
IDs, and artwork references. Track, track total, disc, and disc total are stored
as text, so values such as `A1` or `Side A` survive where the container supports
text numbers. Format-specific mappings are defined per codec.

Optional extended fields are mapped where the container supports them and are
hidden or disabled otherwise: label, catalog number, barcode, release country,
media, script, language, conductor, orchestra, ensemble, work, movement,
movement number, and ReplayGain track/album gain and peak.

### 7.3 Organization template tokens

`{title}`, `{artist}`, `{album_artist}`, `{album}`, `{year}`, `{date}`,
`{genre}`, `{composer}`, `{comment}`, `{label}`, `{catalog}`, `{track}`,
`{track_total}`, `{disc}`, `{disc_total}`, `{disc_dir}`, `{disc_prefix}`, `{format}`, `{bitrate}`, `{ext}`,
plus padding (`{track:02}`), defaults (`{album|Unknown}`), and conditional
segments. Tokens resolve from the edited metadata, not only the on-disk state.
Unknown tokens are rejected during validation.

The default import and organization template is
`{album_artist}/{album}/{disc_prefix}{track:02} {title}` (D-18). `{disc_prefix}` expands to `01-` only for multi-disc albums, so disc numbers prefix the track filename instead of creating folders. `{disc_dir}` remains available for templates that prefer a `Disc N/` folder. It is configurable per library
and editable in the import wizard.

### 7.4 Tracks-compatible identity

Core UUIDs use the Tracks/WebTracks deterministic algorithm. The algorithm is a
compatibility contract and is covered by reference vectors. Tracks never moves
library files, so its IDs are stable by construction; TrackStash does move files,
so it recomputes IDs and remaps references as defined below.

- **ID-01** `stable_uuid(text)` MUST be the uppercase UUID formed from the 16
  MD5 bytes of the UTF-8 text, with no UUID version or variant bits set.
- **ID-02** `library_id = stable_uuid("library|" + canonical_path(root))`.
- **ID-03** `artist_id = stable_uuid("artist|" + lowercase(NFC(name)))`.
- **ID-04** `album_id = stable_uuid("album|" + artist_id + "|" + lowercase(NFC(title)))`.
- **ID-05** `song_id = stable_uuid("song|" + normalized(namespace) + "|" + NFC(relative_path))`.
- **ID-06** `namespace` is a snapshot of the library identifier: trimmed, NFC,
  lowercased. On creation the identifier defaults to `library1`, `library2`, and
  so on, and the namespace is its normalized form. Renaming the identifier MUST
  NOT change the namespace until ReKey.
- **ID-07** Normalization MUST match Swift: NFC, per-character lowercasing (not
  Python's contextual final-sigma rule), strip a leading `/`, and resolve
  symlinks for both the file and the library root.
- **ID-08** Song IDs MUST be recomputed whenever the library-relative path
  changes; every reference MUST be remapped in the same transaction.
- **ID-09** Artist and album IDs MUST be recomputed when their name inputs
  change; affected song rows MUST be updated.
- **ID-10** Library IDs MUST be recomputed when the root path changes. Song IDs
  change only when their library-relative paths change.
- **ID-11** The operation journal MUST record the prior path, names, and
  namespace needed to reverse a remap. No long-term old-ID table is retained.
- **ID-12** Auxiliary entities (operations, saved views, presets) MUST use
  uppercase UUIDv4 values and are not part of the Tracks algorithm.
- **ID-13** ReKey MUST recompute the namespace and all core IDs from current
  paths, remap references, and back up the database before writing.
- **ID-14** External links that embed an old UUID cannot be updated by the
  application. Old IDs are not retained after the operation journal is pruned,
  and the UI MUST warn that external links may break after a move.
- **ID-15** Compatibility tests MUST cover the Tracks/WebTracks reference
  vectors, including the `I.M-P.U.L.S.Σ` lowercase case and non-ASCII paths.

Reference vectors:

```text
song_uuid("iTunes", "Raver Rage Records/レレレコンピ/01 related.m4a")
  = 0B161D2F-A164-B19B-9D78-B2C4B1E72589
artist_uuid("Raver Rage Records")
  = 43054C1F-0026-CD2F-C882-2A741E57531E
album_uuid("43054C1F-0026-CD2F-C882-2A741E57531E", "レレレコンピ")
  = 5411E3DF-F842-42D2-C519-201B354AEA96
swift_lower("I.M-P.U.L.S.Σ") = "i.m-p.u.l.s.σ"
```

---

## 8. Format support matrix

| Format | Read tags | Write tags | Artwork | Notes |
|---|---|---|---|---|
| FLAC | P0 | P0 | P0 | Vorbis comments; native picture blocks. |
| MP3 | P0 | P0 | P0 | ID3v2.3/v2.4; preserve ID3v1 policy. |
| M4A / MP4 (AAC, ALAC) | P0 | P0 | P0 | iTunes-style atoms. |
| OGG Vorbis | P0 | P0 | P1 | Vorbis comments; METADATA_BLOCK_PICTURE. |
| Opus | P0 | P0 | P1 | Vorbis comments. |
| APE / WavPack | P1 | P1 | P1 | Present in the target collection; validate read/write before enabling. |
| WAV | P2 | P2 | P2 | ID3 chunk where supported. |
| AIFF | P2 | P2 | P2 | ID3 chunk. |
| DSF / DFF | P2 | P2 | P2 | Audiophile formats; read-first. |
| MP4 video / MKV | — | — | — | Out of scope in v1 (D-01). |

Priorities reflect the target collection: FLAC, MP3, M4A/AAC/ALAC, OGG/Opus, and
APE/WavPack. TrackStash extends the Tracks scanner with APE/WavPack and uses
mutagen for metadata rather than AVFoundation or ffprobe. Formats outside this
matrix (for example WMA/ASF, MPC, TTA, and Speex) are scanned and listed but
remain disabled for writing until a fixture-backed adapter passes validation.
Unsupported files are never modified.

---

## 9. UX outline

- **Single library:** the active library is managed from Settings → Library and remembered between launches; there is no aggregate All Tracks view or library dropdown in the main window.
- **Right pane:** virtualized track table or album grid with search, format, and
  missing-artwork filters. Track columns can be reordered, auto-fitted, and
  shown/hidden; the layout is persisted and configurable in Settings. Album
  covers resize within fixed column/row gaps to fill the viewport. The album
  grid sorts by date added descending by default; field and order are
  configurable in Settings.
- **Media editor (left):** artwork, editable canonical tags, pending-change
  highlighting, and a fixed Save/Revert row. Multi-selection shows shared values
  and italic `Multiple` placeholders for mixed fields. Save opens a diff preview
  before writing.
- **Action bar:** no main menu bar. Import, undo/redo, refresh, format, artwork
  filtering, view switching, and Settings live in the top bar.
- **Import:** a top-bar Import… button. Scans, adding libraries, relocation, and
  ReKey live in Settings → Library → Manage Libraries.
- **Albums view:** multi-select with drag or ⌘-click for batch tag editing.
- **Track context menu:** Edit Tags, Go to Album, Open, Open with, Delete, and
  Show in Finder.
- **Import wizard:** source picker, tag preview/edit, copy or move mode, destination
  template preview, collision and duplicate handling, per-file progress, and undo.
- **Batch editor:** tri-state fields, mixed-value indicators, transform actions,
  auto-numbering, and a diff preview before saving.
- **Preview dialog:** per-file before/after values, path changes, old and new
  UUIDs, warnings, collision handling, estimated duration, and explicit
  confirmation.
- **Delete dialog:** index-only versus index plus system Trash, file list and
  sizes, and a clear statement of which outcome is reversible.
- **Library Manager:** library identity, namespace, Quick/Full Scan, relocation,
  ReKey, enable/disable, and removal.
- **Progress center:** running and completed operations, cancellable, with a
  per-file error list and an undo action where the operation is reversible.

Primary flows: first-run setup → import or scan → browse → edit → preview → save →
organize/move or delete → undo where reversible. Every destructive action states
whether it can be undone and is reachable from the keyboard.

---

## 10. Proposed architecture

TrackStash is a native desktop application built with Python 3.12+ and PySide6
(Qt 6 Widgets), with a UI-independent core.

- **Core engine (`src/trackstash/core`):** pure Python. Domain types,
  mutagen-based tag I/O, scanner, SQLite index, template engine, journal, and
  duplicate detection. It MUST NOT import PySide6, so a CLI and future ports can
  reuse it.
- **Compatibility layer (`src/trackstash/core/compat`):** a source-level port of
  the Tracks/WebTracks identity algorithm and library enumeration/upsert rules.
  It covers MD5 UUIDs, Swift-compatible lowercasing, namespace snapshots,
  deepest-root ownership, and missing-file review. Reference-vector tests protect
  against drift; there is no runtime dependency on either project.
- **Managed importer (`src/trackstash/core/importing`):** reads tags, accepts
  wizard edits, plans tag-driven destinations, copies or moves files, writes only
  user-edited fields, indexes the result, and journals the operation for undo.
- **Identity and remapping service (`src/trackstash/core/identity`):** computes
  library, artist, album, and song IDs, recomputes them after path or name
  changes, records the prior path/name/namespace needed for undo, and remaps every
  reference in one SQLite transaction.
- **Desktop UI (`src/trackstash/ui`):** PySide6 Widgets. `QMainWindow` shell, a
  SQL-backed `QAbstractTableModel` with a bounded row cache, custom delegates, and
  modal workflows for previews and progress. Search, sorting, and filtering
  execute in SQLite/FTS5 rather than an in-memory proxy, so the view scales to the
  target library size.
- **Platform layer (`src/trackstash/platform`):** Finder reveal (`open -R`),
  trash (`QFile.moveToTrash` or `send2trash`), filesystem watching (`watchdog`),
  and standard paths (`platformdirs`) behind interfaces. Only macOS
  implementations exist in v1; Windows and Linux implementations are added with
  the ports.
- **Tag I/O (mutagen):** supports the formats in Section 8. A format-adapter layer
  per container handles artwork and fields that the easy API does not cover.
  Low-level frame and atom APIs are used for writes that must preserve unknown
  tags; `easy=True` is limited to simple reads. Preservation behavior is verified
  by fixture tests and surfaced in the write preview.
- **Storage (SQLite 3 via the standard library):** a new TrackStash database
  with Tracks-compatible `libraries`, `artists`, `albums`, and `songs` tables
  plus `ts_*` extension tables. WAL mode, foreign keys, versioned migrations, and
  an FTS5 index for search. Existing Tracks/WebTracks databases are not opened or
  migrated. FTS5 availability in the bundled Python is verified at M0; a bundled
  SQLite build is used if the runtime lacks it. Access goes through a thin DAO
  layer; no ORM.
- **Scanner and upsert:** Quick Scan discovers new paths; Full Scan refreshes
  changed files by size and modification time. Hidden files are skipped,
  directory symlinks are not followed, the deepest enabled root owns a file, and
  album grouping falls back from album artist to track artist. These rules and
  the upsert-preservation behavior are ported from Tracks/WebTracks. Metadata is
  read with mutagen, and APE/WavPack support is added.
- **Concurrency:** scanning runs in a `ProcessPoolExecutor` because mutagen
  parsing is CPU-bound and the GIL limits threads. Worker processes return
  JSON-serializable records; a single writer thread owns the database connection.
  Progress is delivered to the UI through Qt signals. Batch writes run in a worker
  thread, and the model is updated in bounded batches on the main thread.
- **Hashing:** `hashlib` SHA-256 over size plus partial head/tail hashing, with
  full hashing deferred until duplicate review or move detection requires it.
- **Artwork:** embedded artwork is read from the selected album's first track
  only when the album enters the viewport, then cached in memory with a bounded
  LRU. No cover files are written to disk; `ts_artwork` tracks per-track embedded
  artwork metadata and `albums.artwork` stays `NULL`.
- **Safety:** the journal records prior tag state, artwork, paths, and IDs before
  any mutation. Imports, moves, organization, tag writes, and index deletions are
  journaled. Index-only deletes are undoable; files moved to the macOS Trash are
  explicitly not app-undoable. Optional full-file backups are configurable.
  Startup recovery detects incomplete operations and offers rollback.
- **Packaging:** `pyproject.toml` with `uv` and a committed `uv.lock`. PySide6 is
  pinned to 6.11.3, whose macOS wheel targets macOS 13; PySide6 6.12+ requires
  macOS 14+. Releases use PyInstaller in one-folder mode with
  `multiprocessing.freeze_support()`, `codesign`, `notarytool`, and a DMG.
  Windows/Linux builds follow with the ports.
- **Testing:** `pytest` for core tests, `pytest-qt` for UI tests, fixture-based
  round-trip tests for every supported format, Tracks/WebTracks UUID reference
  vectors, fixture databases for scan/upsert, import and undo scenarios, a
  generated 10,000-file benchmark library, and `ruff` plus `mypy` in CI.

### Repository layout (proposed)

```
trackstash/
├── pyproject.toml
├── uv.lock
├── README.md
├── LICENSE
├── src/trackstash/
│   ├── core/              # domain, tag I/O, scan, db, organize, journal
│   │   ├── compat/        # Tracks/WebTracks identity and scan rules
│   │   ├── importing/     # managed-library import pipeline
│   │   └── identity/      # UUID generation and remapping
│   ├── ui/                # main window, models, dialogs, widgets
│   ├── platform/
│   │   └── macos/         # Finder reveal, trash, watcher glue
│   ├── cli/               # post-v1
│   └── __main__.py
├── tests/
├── fixtures/
├── docs/
├── packaging/macos/
└── scripts/
```

---

## 11. Milestones

| Milestone | Deliverable | Exit criteria |
|---|---|---|
| **M0** | Requirements sign-off, Python scaffold, CI | D-01 through D-21 confirmed with no open decisions; a clean checkout installs pinned dependencies with `uv`, launches an empty window, and passes `ruff`, `mypy`, and `pytest` in CI. |
| **M1** | Identity and metadata engine | Tracks-compatible UUID reference vectors pass; canonical mapping and mutagen adapters; FLAC/MP3/M4A/OGG/Opus plus APE/WavPack read/write round-trip tests pass; base schema and `ts_*` extensions created; unknown tags and artwork survive where supported; tag snapshots and diffs work. |
| **M2** | Managed library, import, and scan | Import pipeline with tag-driven destinations, copy/move, duplicate and collision handling, journaling; SQLite upsert; quick/full scan; missing review; FTS5 search; a generated 10,000-file library imports and rescans correctly. |
| **M3** | Desktop browsing and import wizard | Library sidebar, SQL-backed virtualized track table, detail panel, search, filters, and the import wizard work on a real library without editing. |
| **M4** | Editing, artwork, update, and history | Single and batch edits with tri-state fields, preview, verified writes, artwork management, journal, undo/redo, update/rescan, and cancellation; crash recovery test passes. |
| **M5** | Organization, deletion, and duplicates | Template moves with live preview, UUID remapping, collision handling, index-only and system-Trash deletion, exact and probable duplicate review; reversible operations are undoable. |
| **M6** | Hardening and release | Watcher, accessibility pass, performance tuning, onboarding, documentation, diagnostics, and a signed/notarized PyInstaller DMG with corresponding source. |

### 11.1 v1 acceptance criteria

| ID | Criterion |
|---|---|
| AC-01 | Scan a 10,000-file mixed-format library, cancel mid-scan, and resume; counts and the error list are correct, and no file is modified. |
| AC-02 | Apply a five-field batch edit to 500 tracks; the preview shows per-file diffs; cancel halfway; completed files remain journaled; undo restores every tag. |
| AC-03 | Round-trip tags and artwork on FLAC, MP3, M4A, OGG, Opus, APE, and WavPack fixtures; unknown fields survive or a warning is shown; the audio stream checksum is unchanged. |
| AC-04 | Organize 1,000 tracks with a template; collisions are reported and resolved; undo restores the original paths. |
| AC-05 | Duplicate review finds exact duplicates by hash and probable duplicates by tags; removal moves files to the macOS Trash or removes them from the index, and never deletes automatically. |
| AC-06 | Kill the application during a batch write; on restart, recovery offers rollback and the library opens in a consistent state. |
| AC-07 | Disconnect an external library root; its tracks are marked offline; reconnect and rescan without data loss. |
| AC-08 | Build the DMG and verify that the corresponding source, third-party notices, and GPL license texts are published with the release, and the app launches on a clean macOS 13+ machine. |
| AC-09 | Cached search and filtering respond within 100 ms at p95 for 100,000 tracks; an initial 10,000-file scan completes within 3 minutes on an SSD. |
| AC-10 | The published source archive matches the DMG version, builds from a clean checkout with `uv`, and produces a launchable application. |
| AC-11 | UUID tests reproduce Tracks/WebTracks reference vectors for library, song, artist, and album IDs, including the `I.M-P.U.L.S.Σ` lowercasing case and non-ASCII paths. |
| AC-12 | Import 100 files from an external folder with copy mode; the source is untouched, destinations follow the tag template, every song ID matches the formula for its final relative path, and undo removes the copies. |
| AC-13 | Move or rename 100 indexed tracks; every song ID is recomputed, all references are updated, no orphan rows remain, and undo restores the prior paths and IDs. |
| AC-14 | Delete 20 tracks index-only and undo restores them; delete 20 tracks with system Trash and the dialog states that file deletion is irreversible. |
| AC-15 | Quick Scan discovers new files, Full Scan refreshes changed files, and missing files are removed only after explicit selection. |
| AC-16 | Import with one edited tag writes only that field, preserves every untouched tag, and leaves the source file unchanged in copy mode. |
| AC-17 | TrackStash creates and writes only its own database; a Tracks/WebTracks `library.sqlite` is never opened or modified. |

### 11.2 Post-M0 backlog

These items are explicitly excluded from M0. Their later milestone placement is
to be decided.

| ID | Item | Notes |
|---|---|---|
| P-01 | Playlist import and management | Section 5.12; requires a `ts_playlists` migration. |
| P-02 | Command-line interface | Section 5.9. |
| P-03 | Windows and Linux ports | The core is kept portable from M0. |
| P-04 | Audio preview | Deferred; not part of v1. |

---

## 12. Decisions

### 12.1 Resolved decisions (2026-10-31)

| ID | Decision | Resolution |
|---|---|---|
| D-01 | Media scope for v1 | **Audio only.** Video is out of scope; the core stays format-agnostic. |
| D-02 | Primary delivery form | **Native desktop GUI.** A CLI follows after v1 using the same core. |
| D-03 | UI framework | **Qt 6 Widgets via PySide6.** Widgets suit data-dense tables and batch workflows better than QML. |
| D-04 | Implementation stack | **Python 3.12+ + PySide6 + mutagen + SQLite.** Swift/AppKit was rejected because portability to Windows/Linux is a stated requirement. |
| D-05 | v1 scope depth | **Full library management:** scan, tags, artwork, organization, duplicates, and undo, delivered by milestone. |
| D-06 | Initial platforms | **macOS only for v1**, with all non-UI code portable and platform services isolated. |
| D-07 | Tag engine and license | **PySide6 + mutagen, application GPL-3.0-only.** Chosen for development speed and mutagen's mature format coverage; the copyleft obligation is accepted. Qt C++ + TagLib remains the alternative for MIT/closed-source distribution. |
| D-08 | Distribution channel | **Direct signed and notarized DMG**, not the Mac App Store, to avoid sandbox restrictions on arbitrary library roots. |
| D-09 | Minimum macOS version | **macOS 13+.** PySide6 is pinned to 6.11.3, whose wheel targets macOS 13; PySide6 6.12+ targets macOS 14+. |
| D-10 | Python toolchain | **Python 3.12+, managed with `uv`.** Dependencies are pinned in `uv.lock`; PySide6 6.11.3 is a direct pin. |
| D-11 | Identity compatibility | **Tracks/WebTracks UUID formulas.** Song IDs are recomputed whenever the relative path changes, all references are remapped transactionally, and only the prior state needed for undo is kept in the operation journal. |
| D-12 | Existing databases | **New TrackStash database only.** Tracks/WebTracks databases are never opened, migrated, or modified. |
| D-13 | Import model | **Managed library.** Copy is the default, move is optional, destinations are tag-driven, and only fields edited in the import wizard are written to files. |
| D-14 | Deletion model | **Index-only by default.** Moving files to the macOS Trash is optional and explicitly irreversible inside the application. |
| D-15 | Schema reuse | **Tracks-compatible `libraries`, `artists`, `albums`, and `songs` tables plus `ts_*` extension tables.** |
| D-16 | Code reuse | **Port/borrow Tracks/WebTracks methods for compatibility** (identity, enumeration, quick/full scan, upsert, missing review, on-demand artwork loading); no runtime dependency on either project. |
| D-17 | Audio preview | **Not in v1.** No playback or preview is implemented; the decision can be revisited later. |
| D-18 | Default import template | **`{album_artist}/{album}/{disc_prefix}{track:02} {title}`**, where `{disc_prefix}` adds `01-` before the track number only for multi-disc albums. Configurable per library and editable in the import wizard. |
| D-19 | Default library location | **`~/Music/TrackStash`**, created on first run and changeable in settings. |
| D-20 | Online metadata | **Not implemented.** TrackStash never performs online metadata lookup; tags come from files, imports, and user edits. |
| D-21 | Playlist import | **Post-M0.** Importing playlists (M3U/M3U8/PLS and similar) is planned after M0 and is not part of the scaffold; milestone placement is TBD. |
| D-22 | Library UI scope | **One current library at a time.** Multiple libraries may exist, but the active library is chosen in Settings and the main window never aggregates tracks from multiple libraries. |

### 12.2 Open decisions

None. All decisions are resolved.

### 12.3 License compliance

- Original source code is released under **GPL-3.0-only**.
- **PySide6** is used under its **GPLv3** option, and **mutagen** is used under
  **GPL-2.0-or-later**, which is compatible with GPLv3.
- The application bundle includes PySide6, Qt, mutagen, Pillow, watchdog,
  platformdirs, and PyInstaller. Every dependency must be GPLv3-compatible, and
  the resolved lockfile is audited before release.
- A `LICENSES/` directory and an About dialog MUST list every third-party
  component, its version, and its license.
- Every binary release MUST be accompanied by the corresponding source (a tagged
  source archive or a public repository link) as required by the GPL.
- The GPL covers original TrackStash code and the combined work; bundled
  dependencies keep their own notices.
- Ported Tracks/WebTracks code MUST come from a copyright holder who can
  relicense it under GPL-3.0-only. Provenance and reference tests are recorded in
  `docs/COMPATIBILITY.md`.
- Release signing requires an Apple Developer Program membership and a Developer
  ID Application certificate; M0–M5 builds use ad-hoc signing.

### 12.4 Key risks

| ID | Risk | Mitigation |
|---|---|---|
| R-01 | Mutagen preserves unknown fields inconsistently across containers. | Round-trip fixtures per format; low-level APIs for writes; snapshot original tags before every write; warn and offer a full-file backup when preservation is uncertain. |
| R-02 | Artwork handling requires format-specific code. | A picture adapter per format with add, replace, and remove tests; on-demand embedded artwork keyed by checksum. |
| R-03 | Python and the GIL can slow scanning, and large libraries can overwhelm an in-memory table model. | Process-pool scanning, SQL-backed model with a bounded cache, FTS5 search, and benchmarks at the 200,000-track target. |
| R-04 | GPL compliance and source publication. | Publish the corresponding source with every binary release; ship notices and license texts; run a dependency-license audit in CI. |
| R-05 | External or network volumes may be slow or disappear during a scan. | Offline state, cancellable scans, bounded concurrency, and no automatic deletion. |
| R-06 | Prebuilt PySide6 wheels or the Python runtime may require a newer macOS than the 13.0 deployment target. | Pin PySide6 6.11.3, verify the wheel tag and `LC_BUILD_VERSION` with `otool`, and test on a macOS 13 machine. |
| R-07 | PyInstaller bundling and notarization add failure modes. | One-folder `.app`, automated build script, hardened runtime, notarization verification, and a clean-machine smoke test. |
| R-08 | Path-based song UUIDs change on every move, breaking external links and references. | Recompute and remap transactionally; record the prior path/name/namespace for undo; show old and new IDs in the preview; warn that external links may break. |
| R-09 | The ported identity or scan rules drift from Tracks/WebTracks. | Reference-vector tests, fixture databases, and a compatibility document; no runtime dependency on either project. |
| R-10 | Import copy/move can lose or corrupt files. | Copy by default, leave the source untouched until commit, journal every file, preview destinations, and verify after write. |
| R-11 | System Trash deletion is not app-undoable. | Index-only is the default; require a separate confirmation and state clearly that file deletion cannot be undone in the app. |
| R-12 | Mutagen metadata mappings differ from Tracks' AVFoundation/ffprobe behavior. | Canonical mapping tests per format; compare against reference metadata for common tags; surface parse warnings. |
| R-13 | A template change can move thousands of files and churn IDs. | Preview the full batch, show ID changes, require confirmation, journal in chunks, and support cancel/undo. |
| R-14 | Ported Tracks/WebTracks code may have unclear provenance. | Confirm copyright ownership before porting, record provenance, and relicense under GPL-3.0 with attribution. |

---

## 13. Review checklist

- [x] Decisions D-01 through D-22 are confirmed.
- [x] Section 2 goals and non-goals match the intended product.
- [x] Section 5 functional requirements are complete and correctly prioritized.
- [x] Section 5.11 import, update, and deletion semantics are correct.
- [x] Section 5.12 playlist import is correctly deferred until after M0 and excluded from the scaffold.
- [x] Section 7 canonical fields and Tracks-compatible identity rules are correct.
- [x] Section 8 format priorities match the actual collection.
- [x] Section 9 UX flows cover the daily workflows.
- [x] Section 10 architecture and repository layout are acceptable.
- [x] Section 11 milestones are ordered correctly.
- [x] Section 11.1 acceptance criteria are testable and complete.
- [x] Section 12.3 GPL compliance and source publication are understood and accepted.
- [x] No open decisions remain.

To review item by item, reply with the requirement IDs to change (for example,
`TAG-07` or `NFR-01`) and the desired adjustment. A section or milestone can be
approved explicitly; unmentioned items remain unchanged.

---

## 14. Approval

| | |
|---|---|
| **Requirements approved** | ☑ Yes  ☐ No — changes requested |
| **Approved by** | Project owner |
| **Date** | 2026-10-31 |
| **Next milestone** | M6 — release hardening and packaging (see `docs/IMPLEMENTATION_STATUS.md`) |
