# Tracks and WebTracks Compatibility

| | |
|---|---|
| **Status** | M0 baseline |
| **Scope** | Identity, schema, scan/import rules, and provenance |
| **Requirements** | `docs/REQUIREMENTS.md` §5.11, §7.1, §7.4 |

TrackStash reuses implementation methods from the existing Tracks macOS app
(`../tracks`) and its Python companion WebTracks (`../webtracks`). The two
upstream projects share a deterministic identity algorithm, a SQLite schema, and
a set of scan rules. TrackStash ports the parts needed for a compatible managed
library, but has **no runtime dependency** on either project.

## 1. What is ported

- The `stableUUID` identity algorithm and all core entity formulas.
- Swift-compatible Unicode normalization and lowercasing.
- The Tracks-compatible `libraries`, `artists`, `albums`, and `songs` table layout.
- Quick Scan and Full Scan discovery rules.
- Upsert behavior that preserves user metadata.
- Missing-file review rules.
- On-demand album artwork loading from embedded tags.

## 2. What is not ported

- Playback, queue, MPD, web serving, and Tracks UI code.
- The Tracks/WebTracks database itself. TrackStash creates a new database and
  never opens, migrates, or writes an upstream `library.sqlite`.
- Playlist management. Playlist import is a post-M0 feature
  (`docs/REQUIREMENTS.md` §5.12).
- Online metadata lookup. TrackStash performs none.

## 3. Stable identity

### 3.1 Hash

```text
stable_uuid(text) = UUID( MD5(UTF-8(text)) )
```

The 16 MD5 bytes are used directly as the UUID bytes. No version or variant bits
are set. IDs are stored and displayed as uppercase UUID strings.

### 3.2 Core formulas

```text
library = stable_uuid("library|" + canonical_path(root))
artist  = stable_uuid("artist|"  + lowercase(NFC(name)))
album   = stable_uuid("album|"   + artist_id + "|" + lowercase(NFC(title)))
song    = stable_uuid("song|"    + normalized(namespace) + "|" + NFC(relative_path))
```

`namespace` is a snapshot of the library identifier: trimmed, NFC-normalized,
and lowercased. The identifier defaults to `library1`, `library2`, and so on.
Renaming the identifier does not change the namespace until ReKey runs.

`relative_path` is the file path relative to the library root. Both the file and
the root are resolved through symlinks. The path is NFC-normalized and has any
leading `/` removed.

### 3.3 Swift-compatible lowercasing

Tracks uses Swift's locale-independent `lowercased()`, which applies a
context-free per-character mapping. Python's `str.lower()` applies the Unicode
final-sigma rule in word contexts. TrackStash lowercases one character at a time:

```python
"".join(character.lower() for character in value)
```

### 3.4 Reference vectors

```text
song_uuid("iTunes", "Raver Rage Records/レレレコンピ/01 related.m4a")
  = 0B161D2F-A164-B19B-9D78-B2C4B1E72589
artist_uuid("Raver Rage Records")
  = 43054C1F-0026-CD2F-C882-2A741E57531E
album_uuid("43054C1F-0026-CD2F-C882-2A741E57531E", "レレレコンピ")
  = 5411E3DF-F842-42D2-C519-201B354AEA96
swift_lower("I.M-P.U.L.S.Σ") = "i.m-p.u.l.s.σ"
```

These vectors are copied from the WebTracks compatibility tests and MUST remain
green in TrackStash.

### 3.5 Path changes

Tracks never moves library files, so its song IDs are stable by construction.
TrackStash is a managed library and does move files. When a file's
library-relative path changes:

1. The new song ID is computed from the new path.
2. `songs.id` and `songs.path` are updated.
3. Every `ts_*` reference is updated in the same transaction.
4. The operation journal records the prior path, names, and namespace needed to
   reverse the change.
5. Old IDs are not retained in a long-term alias table. External links that embed
   an old ID will stop resolving, and the UI warns about this before a move.

## 4. Schema

TrackStash creates a new SQLite database with Tracks-compatible base tables:

```sql
libraries(id, path, kind, name, identifier, id_namespace, date_added, enabled)
artists(id, name)
albums(id, title, artist_id, genre, year, artwork)
songs(id, path, library_id, title, artist_id, album_id, genre, year,
      track, track_total, disc, disc_total, comments, duration, date_added,
      play_count, rating, loved, last_played, skip_count, mtime, file_size)
```

`albums.artwork` remains `NULL`; artwork is read from embedded tags on demand
for visible albums and is not cached on disk.

TrackStash-specific data lives in `ts_*` tables:

- `ts_song_tags` — extended scalar tags.
- `ts_audio_properties` — format, codec, bitrate, sample rate, channels, bit depth.
- `ts_file_state` — content hash, hash state, scan error, offline flag.
- `ts_tag_value` — multi-value and unknown/custom tags.
- `ts_artwork` — per-track embedded artwork metadata (no disk cache).
- `ts_operations` / `ts_operation_items` — journal and reversible prior state.
- `ts_track_fts` — FTS5 search index.
- `ts_saved_views`, `ts_presets`, `ts_settings` — user configuration.

## 5. Scan and upsert rules

Ported from Tracks/WebTracks:

- Supported base extensions are FLAC, MP3, M4A, WAV, AIFF, OGG, and Opus.
  TrackStash adds APE and WavPack.
- Hidden files and directories are skipped. Directory symlinks are not followed.
  Files and roots are canonicalized.
- Quick Scan discovers new paths only. Full Scan also refreshes files whose size
  or modification time changed.
- When library roots overlap, the deepest enabled root owns the file.
- The album artist falls back to the track artist. Albums are grouped by album
  artist plus the lowercased album title.
- `date_added` is the file modification time, or the first-seen time when it is
  zero, and is preserved across rescans.
- Upserts update tags, duration, modification time, and file size while
  preserving play counts, stars, ratings, last-played time, and skip counts.
- Missing files are reviewed; only explicitly selected rows are removed. A scan
  never deletes files.
- Artwork is loaded from embedded tags for visible albums and cached in memory
  only; no cover files are written to disk.

TrackStash-specific behavior:

- Imports copy by default and may move on request. Files are organized by tags
  using the default template `{artist_folder}/{album}/{disc_prefix}{track_prefix}{title}`. `{artist_folder}` is `Compilations` for compilations and the album artist otherwise. `{disc_prefix}` inserts `N-` when the disc number is above zero and the disc total is not 1. `{track_prefix}` inserts `NN ` only when a track number is present. These rules match Apple Music's observed behavior (`docs/ITUNES_NAMING_ANALYSIS.md`).
- Only tags edited in the import wizard are written back to the imported file.
- Tag writes use mutagen and preserve unknown tags where the container supports
  them.
- Deletion removes the index by default; moving files to the macOS Trash is an
  explicit, non-undoable option.
- APE and WavPack are supported through mutagen.

## 6. Provenance and licensing

The upstream `tracks` and `webtracks` repositories are private project sources
without standalone license files. Code ported into TrackStash must be contributed
by a copyright holder who can relicense it under GPL-3.0-only. Provenance is
recorded here and in release notices.

TrackStash itself is GPL-3.0-only. The corresponding source must be published
with every binary release.
