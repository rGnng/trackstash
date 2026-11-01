"""Managed-library operations: import, scan, edit, organize, delete, undo."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from send2trash import send2trash

from trackstash.core.artwork import normalize_artwork
from trackstash.core.db import Database, Library, Track
from trackstash.core.identity import (
    canonical_path,
    normalize_identifier,
    relative_path,
    song_uuid,
)
from trackstash.core.metadata import (
    TagSet,
    TrackMetadata,
    apply_tag_edits,
    read_metadata,
    remove_artwork,
    supported_extensions,
    tagset_to_dict,
    write_artwork,
    write_tags,
)
from trackstash.core.template import (
    DEFAULT_TEMPLATE,
    render_template,
    with_collision_suffix,
)

Progress = Callable[[str, int, int, str], None]


@dataclass(slots=True)
class ImportPlanItem:
    """One source file and its planned destination."""

    source: Path
    destination: Path
    relative_path: str
    metadata: TrackMetadata
    tags: TagSet
    edits: dict[str, object] = field(default_factory=dict)
    action: str = "import"
    in_place: bool = False
    collision: bool = False
    duplicate_of: str | None = None
    replace_track_id: str | None = None
    warning: str = ""


@dataclass(slots=True)
class ImportPlan:
    """A previewable import plan."""

    library: Library
    items: list[ImportPlanItem]
    errors: list[str]
    mode: str = "copy"
    template: str = DEFAULT_TEMPLATE


@dataclass(slots=True)
class ImportResult:
    """Result of executing an import plan."""

    operation_id: str
    imported: list[Track]
    skipped: list[str]
    errors: list[str]
    copied: int
    moved: int
    undoable: bool


@dataclass(slots=True)
class ScanResult:
    """Result of a quick or full scan."""

    operation_id: str
    discovered: int
    updated: int
    missing: list[str]
    errors: list[str]
    pruned: int = 0


@dataclass(slots=True)
class TagChange:
    """A previewed tag change for one track."""

    song_id: str
    path: str
    before: TagSet
    after: TagSet
    changed_fields: list[str]
    warning: str = ""


@dataclass(slots=True)
class TagUpdateResult:
    """Result of a tag update operation."""

    operation_id: str
    updated: list[Track]
    errors: list[str]


@dataclass(slots=True)
class OrganizePlanItem:
    """A planned file move."""

    song_id: str
    library_id: str
    old_path: str
    new_path: str
    old_id: str
    new_id: str
    collision: bool = False
    unchanged: bool = False
    warning: str = ""


@dataclass(slots=True)
class OrganizeResult:
    """Result of an organization operation."""

    operation_id: str
    moved: list[Track]
    errors: list[str]
    undoable: bool


@dataclass(slots=True)
class DeleteResult:
    """Result of a deletion operation."""

    operation_id: str
    deleted: int
    trashed: int
    errors: list[str]
    undoable: bool


@dataclass(slots=True)
class UndoResult:
    """Result of undoing the latest operation."""

    operation_id: str
    kind: str
    undone: int
    errors: list[str]


@dataclass(slots=True)
class RekeyResult:
    """Result of recomputing a library namespace and its song IDs."""

    library_id: str
    namespace: str
    updated: int
    backup: str


def content_hash(path: str | Path, sample_size: int = 1024 * 1024) -> str:
    """Return a fast fingerprint using size plus head and tail samples."""
    value = Path(path)
    stat = value.stat()
    digest = hashlib.sha256()
    digest.update(str(stat.st_size).encode("ascii"))
    with value.open("rb") as handle:
        digest.update(handle.read(sample_size))
        if stat.st_size > sample_size * 2:
            handle.seek(-sample_size, os.SEEK_END)
            digest.update(handle.read(sample_size))
    return digest.hexdigest()


def full_content_hash(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    """Return the full SHA-256 digest of a file for duplicate confirmation."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def collect_audio_files(root: str | Path) -> list[Path]:
    """Collect supported audio files, skipping hidden entries and directory links."""
    value = Path(root).expanduser()
    if value.is_file():
        return (
            [Path(canonical_path(str(value)))]
            if value.suffix.lower() in supported_extensions()
            else []
        )
    if not value.is_dir():
        raise ValueError(f"Source does not exist: {value}")
    result: list[Path] = []
    for current, directories, files in os.walk(value, followlinks=False):
        directories[:] = [
            name
            for name in directories
            if not name.startswith(".") and not os.path.islink(os.path.join(current, name))
        ]
        for name in files:
            if name.startswith(".") or name.startswith("._"):
                continue
            path = Path(current) / name
            if path.suffix.lower() in supported_extensions() and path.is_file():
                result.append(Path(canonical_path(str(path))))
    return sorted(result)


class LibraryService:
    """High-level operations over a managed TrackStash database."""

    def __init__(
        self,
        db: Database,
        *,
        default_template: str = DEFAULT_TEMPLATE,
        strong_order: bool = False,
        preserve_mtime: bool = True,
        artwork_max_size: int = 1000,
        artwork_quality: int = 90,
        artwork_aspect: str = "crop",
    ) -> None:
        self.db = db
        self.default_template = default_template
        self.strong_order = strong_order
        self.preserve_mtime = preserve_mtime
        self.artwork_max_size = artwork_max_size
        self.artwork_quality = artwork_quality
        self.artwork_aspect = artwork_aspect

    # ------------------------------------------------------------------
    # Import

    def plan_import(
        self,
        sources: Sequence[str | Path],
        library_id: str,
        *,
        mode: str = "copy",
        template: str | None = None,
        common_edits: Mapping[str, object] | None = None,
        edits_by_source: Mapping[str, Mapping[str, object]] | None = None,
        duplicate_policy: str = "skip",
        progress: Progress | None = None,
    ) -> ImportPlan:
        library = self.db.get_library(library_id)
        if library is None:
            raise ValueError("Library not found")
        if mode not in {"copy", "move"}:
            raise ValueError("Import mode must be copy or move")
        if duplicate_policy not in {"skip", "keep", "replace"}:
            raise ValueError("Unknown duplicate policy")
        template = template or self.default_template
        edits_by_source = edits_by_source or {}
        common_edits = common_edits or {}

        files: list[Path] = []
        for source in sources:
            files.extend(collect_audio_files(source))
        items: list[ImportPlanItem] = []
        errors: list[str] = []
        seen_destinations: set[str] = set()
        total = len(files)

        for index, source in enumerate(files):
            if progress:
                progress("Planning import", index, total, str(source))
            try:
                metadata = read_metadata(source)
            except Exception as exc:
                errors.append(f"{source}: {exc}")
                continue
            edits = dict(common_edits)
            edits.update(edits_by_source.get(str(source), {}))
            tags = apply_tag_edits(metadata.tags, edits)

            source_path = canonical_path(str(source))
            in_place = source_path == canonical_path(library.path) or source_path.startswith(
                canonical_path(library.path).rstrip("/") + "/"
            )
            if in_place:
                destination = Path(source_path)
                rel = relative_path(source_path, library.path)
                if rel is None:
                    errors.append(f"{source}: not under the selected library")
                    continue
                existing = self.db.get_track_by_path(source_path)
                if existing is not None:
                    items.append(
                        ImportPlanItem(
                            source=source,
                            destination=destination,
                            relative_path=rel,
                            metadata=metadata,
                            tags=tags,
                            edits=edits,
                            action="skip",
                            in_place=True,
                            duplicate_of=existing.id,
                            warning="Already indexed",
                        )
                    )
                    continue
            else:
                rel = render_template(template, tags, metadata, extension=source.suffix.lower())
                destination = Path(library.path) / rel
                duplicate = self.db.find_by_content_hash(content_hash(source))
                if duplicate is not None and duplicate_policy == "skip":
                    items.append(
                        ImportPlanItem(
                            source=source,
                            destination=destination,
                            relative_path=rel,
                            metadata=metadata,
                            tags=tags,
                            edits=edits,
                            action="skip",
                            duplicate_of=duplicate.id,
                            warning="Duplicate content already in the library",
                        )
                    )
                    continue
                if duplicate is not None and duplicate_policy == "replace":
                    items.append(
                        ImportPlanItem(
                            source=source,
                            destination=Path(duplicate.path),
                            relative_path=relative_path(duplicate.path, library.path) or rel,
                            metadata=metadata,
                            tags=tags,
                            edits=edits,
                            action="replace",
                            duplicate_of=duplicate.id,
                            replace_track_id=duplicate.id,
                            warning="Existing duplicate will be moved to the Trash",
                        )
                    )
                    continue

            destination_key = str(destination)
            collision = destination.exists() or destination_key in seen_destinations
            if collision or self.db.get_track_by_path(str(destination)) is not None:
                if duplicate_policy == "replace":
                    collision = True
                else:
                    counter = 2
                    candidate = destination
                    while (
                        candidate.exists()
                        or str(candidate) in seen_destinations
                        or self.db.get_track_by_path(str(candidate)) is not None
                    ):
                        rel = with_collision_suffix(rel, counter)
                        candidate = Path(library.path) / rel
                        counter += 1
                    destination = candidate
                    destination_key = str(destination)
                    collision = True
            seen_destinations.add(destination_key)
            items.append(
                ImportPlanItem(
                    source=source,
                    destination=destination,
                    relative_path=rel,
                    metadata=metadata,
                    tags=tags,
                    edits=edits,
                    action="import",
                    in_place=in_place,
                    collision=collision,
                )
            )

        if progress:
            progress("Planning import", total, total, f"{len(items)} files")
        return ImportPlan(library=library, items=items, errors=errors, mode=mode, template=template)

    def execute_import(self, plan: ImportPlan, *, progress: Progress | None = None) -> ImportResult:
        library = plan.library
        operation_id = self.db.create_operation(
            "import",
            f"Import {len(plan.items)} files into {library.name}",
            undoable=True,
        )
        imported: list[Track] = []
        skipped: list[str] = []
        errors = list(plan.errors)
        copied = 0
        moved = 0
        undoable = True
        total = len(plan.items)

        for index, item in enumerate(plan.items):
            if progress:
                progress("Importing", index, total, str(item.source))
            if item.action == "skip":
                skipped.append(str(item.source))
                continue
            destination = item.destination
            replaced: Track | None = None
            file_written = False
            try:
                if item.action == "replace" and item.replace_track_id:
                    replaced = self.db.get_track(item.replace_track_id)
                    if replaced is not None:
                        send2trash(replaced.path)
                        self.db.delete_tracks([replaced.id])
                        undoable = False
                if not item.in_place:
                    if plan.mode == "copy":
                        self._atomic_copy(item.source, destination)
                        copied += 1
                    else:
                        self._safe_move(item.source, destination)
                        moved += 1
                    file_written = True
                if item.edits:
                    write_tags(destination, item.edits)
                metadata = read_metadata(destination)
                tracks = self.db.upsert_tracks([metadata], library)
                if not tracks:
                    raise RuntimeError("Track was not indexed")
                track = tracks[0]
                self.db.update_content_hash(track.id, content_hash(destination))
                self.db.add_operation_item(
                    operation_id,
                    song_id=track.id,
                    path=str(destination),
                    prior={
                        "source": str(item.source),
                        "destination": str(destination),
                        "mode": plan.mode,
                        "in_place": item.in_place,
                        "action": item.action,
                        "replaced_track_id": item.replace_track_id,
                        "library_id": library.id,
                        "tags": tagset_to_dict(item.tags),
                    },
                    result={"track_id": track.id, "path": track.path},
                )
                imported.append(track)
            except Exception as exc:
                errors.append(f"{item.source}: {exc}")
                self.db.add_operation_item(
                    operation_id,
                    song_id=item.replace_track_id,
                    path=str(destination),
                    prior={"source": str(item.source), "mode": plan.mode},
                    error=str(exc),
                )
                if file_written and not item.in_place:
                    try:
                        if plan.mode == "copy":
                            destination.unlink()
                        elif plan.mode == "move" and not item.source.exists():
                            self._safe_move(destination, item.source)
                    except OSError:
                        pass
        self.db.finish_operation(operation_id)
        if progress:
            progress("Importing", total, total, f"{len(imported)} imported")
        return ImportResult(
            operation_id=operation_id,
            imported=imported,
            skipped=skipped,
            errors=errors,
            copied=copied,
            moved=moved,
            undoable=undoable,
        )

    def _atomic_copy(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.trackstash-{uuid.uuid4().hex}.tmp")
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
        except Exception:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise

    def _safe_move(self, source: Path, destination: Path) -> None:
        if canonical_path(str(source)) == canonical_path(str(destination)):
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.trackstash-{uuid.uuid4().hex}.tmp")
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
            source.unlink()
        except Exception:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Scan

    def scan_library(
        self,
        library_id: str,
        *,
        mode: str = "quick",
        prune: bool = False,
        progress: Progress | None = None,
    ) -> ScanResult:
        library = self.db.get_library(library_id)
        if library is None:
            raise ValueError("Library not found")
        if mode not in {"quick", "full"}:
            raise ValueError("Scan mode must be quick or full")
        operation_id = self.db.create_operation(
            "scan", f"{mode.title()} scan of {library.name}", undoable=False
        )
        files = collect_audio_files(library.path)
        discovered = {str(path) for path in files}
        known = self.db.paths_for_library(library.id)
        pending: list[Path] = []
        for path in files:
            known_entry = known.get(str(path))
            if known_entry is None:
                pending.append(path)
            elif mode == "full":
                _, mtime, size = known_entry
                stat = path.stat()
                if abs(mtime - stat.st_mtime) >= 1 or size != stat.st_size:
                    pending.append(path)
        errors: list[str] = []
        metadata_list: list[TrackMetadata] = []
        if progress:
            progress("Reading metadata", 0, len(pending), "")
        workers = min(8, max(1, (os.cpu_count() or 2)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(read_metadata, path): path for path in pending}
            for index, future in enumerate(as_completed(futures), start=1):
                path = futures[future]
                try:
                    metadata_list.append(future.result())
                except Exception as exc:
                    errors.append(f"{path}: {exc}")
                if progress:
                    progress("Reading metadata", index, len(pending), str(path))
        missing = [path for path in known if path not in discovered]
        missing_set = set(missing)
        known_by_id = {value[0]: path for path, value in known.items()}
        known_hashes = self.db.hash_map(library.id)
        moved_old_paths: set[str] = set()
        for metadata in metadata_list:
            try:
                digest = content_hash(metadata.path)
            except OSError:
                digest = ""
            old_id = known_hashes.get(digest) if digest else None
            old_path = known_by_id.get(old_id or "")
            if old_id and old_path in missing_set:
                rel = relative_path(metadata.path, library.path)
                if rel is not None:
                    new_id = song_uuid(library.id_namespace, rel)
                    try:
                        self.db.move_song(old_id, metadata.path, new_id)
                        moved_old_paths.add(old_path)
                    except Exception as exc:
                        errors.append(f"{metadata.path}: {exc}")
        missing = [path for path in missing if path not in moved_old_paths]
        if progress:
            progress("Updating database", 0, len(metadata_list), "")
        tracks = self.db.upsert_tracks(metadata_list, library)
        for index, track in enumerate(tracks, start=1):
            try:
                self.db.update_content_hash(track.id, content_hash(track.path))
            except OSError:
                pass
            if progress:
                progress("Updating database", index, len(tracks), track.path)
        pruned = 0
        if prune and missing:
            missing_ids = [known[path][0] for path in missing if path in known]
            pruned = self.db.delete_tracks(missing_ids)
        self.db.finish_operation(operation_id)
        return ScanResult(
            operation_id=operation_id,
            discovered=len(discovered),
            updated=len(tracks),
            missing=missing,
            errors=errors,
            pruned=pruned,
        )

    # ------------------------------------------------------------------
    # Tag editing

    def preview_tag_edits(
        self, song_ids: Sequence[str], edits: Mapping[str, object]
    ) -> list[TagChange]:
        changes: list[TagChange] = []
        for song_id in song_ids:
            track = self.db.get_track(song_id)
            tags = self.db.load_tag_set(song_id)
            if track is None or tags is None:
                continue
            before = tagset_to_dict(tags)
            after = apply_tag_edits(tags, edits)
            changed = [
                key for key, value in tagset_to_dict(after).items() if before.get(key) != value
            ]
            warning = ""
            path = Path(track.path)
            if not path.exists():
                warning = "File is missing"
            else:
                stat = path.stat()
                if abs(stat.st_mtime - track.mtime) >= 1 or stat.st_size != track.file_size:
                    warning = "File changed on disk since indexing"
            changes.append(
                TagChange(
                    song_id=song_id,
                    path=track.path,
                    before=tags,
                    after=after,
                    changed_fields=changed,
                    warning=warning,
                )
            )
        return changes

    def preview_auto_number(
        self,
        song_ids: Sequence[str],
        *,
        per_disc: bool = True,
        start: int = 1,
    ) -> list[TagChange]:
        """Preview sequential track numbers, grouped per album/disc."""
        tracks = [track for song_id in song_ids if (track := self.db.get_track(song_id))]
        groups: dict[tuple[str, str], list[Track]] = {}
        for track in tracks:
            key = (track.album_id, track.disc if per_disc else "")
            groups.setdefault(key, []).append(track)
        changes: list[TagChange] = []
        for group in groups.values():
            group.sort(
                key=lambda item: (
                    int(item.track) if item.track.isdigit() else 9999,
                    item.title.casefold(),
                    item.path,
                )
            )
            total = len(group)
            for offset, track in enumerate(group):
                tags = self.db.load_tag_set(track.id)
                if tags is None:
                    continue
                after = apply_tag_edits(
                    tags,
                    {"track": str(start + offset), "track_total": str(total)},
                )
                before = tagset_to_dict(tags)
                changed = [
                    key for key, value in tagset_to_dict(after).items() if before.get(key) != value
                ]
                changes.append(
                    TagChange(
                        song_id=track.id,
                        path=track.path,
                        before=tags,
                        after=after,
                        changed_fields=changed,
                    )
                )
        return changes

    def auto_number_tracks(
        self,
        song_ids: Sequence[str],
        *,
        per_disc: bool = True,
        start: int = 1,
        progress: Progress | None = None,
    ) -> TagUpdateResult:
        changes = self.preview_auto_number(song_ids, per_disc=per_disc, start=start)
        operation_id = self.db.create_operation(
            "tags", f"Auto-number {len(changes)} tracks", undoable=True
        )
        updated: list[Track] = []
        errors: list[str] = []
        total = len(changes)
        for index, change in enumerate(changes, start=1):
            if progress:
                progress("Auto-numbering", index - 1, total, change.path)
            if not change.changed_fields:
                continue
            try:
                track = self.db.get_track(change.song_id)
                if track is None:
                    raise ValueError("Track not found")
                path = Path(track.path)
                if not path.exists():
                    raise FileNotFoundError(track.path)
                before = tagset_to_dict(change.before)
                edits = {
                    "track": change.after.track,
                    "track_total": change.after.track_total,
                }
                stat_before = path.stat()
                write_tags(path, edits)
                self._restore_mtime(path, stat_before)
                metadata = read_metadata(path)
                library = self.db.get_library(track.library_id or "")
                if library is None:
                    raise ValueError("Library not found")
                written = self.db.upsert_tracks([metadata], library)
                if not written:
                    raise RuntimeError("Track was not indexed after numbering")
                track = written[0]
                self.db.add_operation_item(
                    operation_id,
                    song_id=track.id,
                    path=track.path,
                    prior={"tags": before, "path": track.path, "library_id": library.id},
                    result={"tags": tagset_to_dict(metadata.tags)},
                )
                updated.append(track)
            except Exception as exc:
                errors.append(f"{change.path}: {exc}")
                self.db.add_operation_item(
                    operation_id,
                    song_id=change.song_id,
                    path=change.path,
                    error=str(exc),
                )
        self.db.finish_operation(operation_id)
        if progress:
            progress("Auto-numbering", total, total, "")
        updated = self._strong_organize(updated, errors)
        return TagUpdateResult(operation_id=operation_id, updated=updated, errors=errors)

    def _restore_mtime(self, path: Path, stat: os.stat_result) -> None:
        if not self.preserve_mtime:
            return
        try:
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        except OSError:
            pass

    def _strong_organize(self, tracks: Sequence[Track], errors: list[str]) -> list[Track]:
        if not self.strong_order or not tracks:
            return list(tracks)
        items = self.preview_organize([track.id for track in tracks])
        movable: list[OrganizePlanItem] = []
        by_old_id: dict[str, OrganizePlanItem] = {}
        destinations: set[str] = set()
        for item in items:
            if item.unchanged:
                continue
            if item.collision:
                errors.append(f"{item.old_path}: destination already exists")
                continue
            if item.new_path in destinations:
                errors.append(f"{item.old_path}: duplicate destination {item.new_path}")
                continue
            destinations.add(item.new_path)
            movable.append(item)
            by_old_id[item.old_id] = item
        if not movable:
            return list(tracks)
        result = self.organize(movable)
        errors.extend(result.errors)
        final: list[Track] = []
        for track in tracks:
            moved_item = by_old_id.get(track.id)
            current = self.db.get_track(moved_item.new_id if moved_item is not None else track.id)
            if current is not None:
                final.append(current)
        return final

    def update_tags(
        self,
        song_ids: Sequence[str],
        edits: Mapping[str, object],
        *,
        progress: Progress | None = None,
    ) -> TagUpdateResult:
        operation_id = self.db.create_operation(
            "tags", f"Edit tags for {len(song_ids)} tracks", undoable=True
        )
        updated: list[Track] = []
        errors: list[str] = []
        total = len(song_ids)
        for index, song_id in enumerate(song_ids, start=1):
            if progress:
                progress("Writing tags", index - 1, total, song_id)
            try:
                track = self.db.get_track(song_id)
                tags = self.db.load_tag_set(song_id)
                if track is None or tags is None:
                    raise ValueError("Track not found")
                path = Path(track.path)
                if not path.exists():
                    raise FileNotFoundError(track.path)
                stat = path.stat()
                if abs(stat.st_mtime - track.mtime) >= 1 or stat.st_size != track.file_size:
                    raise RuntimeError("File changed on disk; rescan before editing")
                before = tagset_to_dict(tags)
                stat_before = path.stat()
                write_tags(path, edits)
                self._restore_mtime(path, stat_before)
                metadata = read_metadata(path)
                library = self.db.get_library(track.library_id or "")
                if library is None:
                    raise ValueError("Library not found")
                written = self.db.upsert_tracks([metadata], library)
                if not written:
                    raise RuntimeError("Track was not indexed after writing tags")
                track = written[0]
                self.db.add_operation_item(
                    operation_id,
                    song_id=track.id,
                    path=track.path,
                    prior={
                        "tags": before,
                        "path": track.path,
                        "library_id": library.id,
                    },
                    result={"tags": tagset_to_dict(metadata.tags)},
                )
                updated.append(track)
            except Exception as exc:
                errors.append(f"{song_id}: {exc}")
                self.db.add_operation_item(
                    operation_id,
                    song_id=song_id,
                    path="",
                    error=str(exc),
                )
            if progress:
                progress("Writing tags", index, total, "")
        self.db.finish_operation(operation_id)
        updated = self._strong_organize(updated, errors)
        return TagUpdateResult(operation_id=operation_id, updated=updated, errors=errors)

    # ------------------------------------------------------------------
    # Organization

    def preview_organize(
        self, song_ids: Sequence[str], template: str | None = None
    ) -> list[OrganizePlanItem]:
        template = template or self.default_template
        items: list[OrganizePlanItem] = []
        for song_id in song_ids:
            track = self.db.get_track(song_id)
            tags = self.db.load_tag_set(song_id)
            if track is None or tags is None or track.library_id is None:
                continue
            library = self.db.get_library(track.library_id)
            if library is None:
                continue
            metadata = read_metadata(track.path)
            rel = render_template(template, tags, metadata, extension=Path(track.path).suffix)
            new_path = str(Path(library.path) / rel)
            new_id = song_uuid(library.id_namespace, rel)
            collision = False
            if new_path != track.path:
                existing = self.db.get_track_by_path(new_path)
                collision = Path(new_path).exists() or (
                    existing is not None and existing.id != track.id
                )
            items.append(
                OrganizePlanItem(
                    song_id=track.id,
                    library_id=library.id,
                    old_path=track.path,
                    new_path=new_path,
                    old_id=track.id,
                    new_id=new_id,
                    collision=collision,
                    unchanged=canonical_path(new_path) == canonical_path(track.path),
                )
            )
        return items

    def organize(
        self,
        items: Sequence[OrganizePlanItem],
        *,
        progress: Progress | None = None,
    ) -> OrganizeResult:
        operation_id = self.db.create_operation(
            "organize", f"Organize {len(items)} tracks", undoable=True
        )
        moved: list[Track] = []
        errors: list[str] = []
        total = len(items)
        for index, item in enumerate(items, start=1):
            if progress:
                progress("Organizing", index - 1, total, item.old_path)
            if item.unchanged:
                continue
            if item.collision:
                errors.append(f"{item.old_path}: destination already exists")
                continue
            try:
                source = Path(item.old_path)
                destination = Path(item.new_path)
                if not source.exists():
                    raise FileNotFoundError(item.old_path)
                self._safe_move(source, destination)
                track = self.db.move_song(item.song_id, item.new_path, item.new_id)
                self.db.add_operation_item(
                    operation_id,
                    song_id=item.new_id,
                    path=item.new_path,
                    prior={
                        "old_path": item.old_path,
                        "new_path": item.new_path,
                        "old_id": item.old_id,
                        "new_id": item.new_id,
                        "library_id": item.library_id,
                    },
                    result={"track_id": track.id},
                )
                moved.append(track)
            except Exception as exc:
                errors.append(f"{item.old_path}: {exc}")
                self.db.add_operation_item(
                    operation_id,
                    song_id=item.song_id,
                    path=item.old_path,
                    error=str(exc),
                )
            if progress:
                progress("Organizing", index, total, "")
        self.db.finish_operation(operation_id)
        return OrganizeResult(operation_id=operation_id, moved=moved, errors=errors, undoable=True)

    # ------------------------------------------------------------------
    # Deletion

    def delete_tracks(
        self,
        song_ids: Sequence[str],
        *,
        delete_files: bool = False,
        progress: Progress | None = None,
    ) -> DeleteResult:
        operation_id = self.db.create_operation(
            "delete",
            f"Delete {len(song_ids)} tracks"
            + (" and move files to the Trash" if delete_files else " from the index"),
            undoable=not delete_files,
        )
        deleted = 0
        trashed = 0
        errors: list[str] = []
        total = len(song_ids)
        for index, song_id in enumerate(song_ids, start=1):
            if progress:
                progress("Deleting", index - 1, total, song_id)
            track = self.db.get_track(song_id)
            if track is None:
                continue
            try:
                if delete_files:
                    send2trash(track.path)
                    trashed += 1
                self.db.add_operation_item(
                    operation_id,
                    song_id=song_id,
                    path=track.path,
                    prior={
                        "track_id": song_id,
                        "path": track.path,
                        "library_id": track.library_id,
                        "tags": tagset_to_dict(self.db.load_tag_set(song_id) or TagSet()),
                    },
                    result={"trashed": delete_files},
                )
                deleted += self.db.delete_tracks([song_id])
            except Exception as exc:
                errors.append(f"{track.path}: {exc}")
            if progress:
                progress("Deleting", index, total, "")
        self.db.finish_operation(operation_id)
        return DeleteResult(
            operation_id=operation_id,
            deleted=deleted,
            trashed=trashed,
            errors=errors,
            undoable=not delete_files,
        )

    def delete_library(self, library_id: str) -> int:
        return self.db.delete_library_rows(library_id)

    # ------------------------------------------------------------------
    # Duplicates

    def exact_duplicates(self) -> list[list[Track]]:
        """Return duplicate groups confirmed by a full content hash."""
        groups = self.db.exact_duplicate_groups()
        confirmed: list[list[Track]] = []
        for group in groups:
            by_hash: dict[str, list[Track]] = {}
            for track in group:
                try:
                    digest = full_content_hash(track.path)
                except OSError:
                    continue
                by_hash.setdefault(digest, []).append(track)
            confirmed.extend(items for items in by_hash.values() if len(items) > 1)
        return confirmed

    # ------------------------------------------------------------------
    # ReKey and artwork

    def rekey_library(self, library_id: str) -> RekeyResult:
        library = self.db.get_library(library_id)
        if library is None:
            raise ValueError("Library not found")
        namespace = normalize_identifier(library.identifier)
        if not namespace:
            raise ValueError("Library identifier must not be empty")
        tracks = self.db.list_tracks(library_id=library.id)
        planned: list[tuple[Track, str]] = []
        seen: set[str] = set()
        for track in tracks:
            rel = relative_path(track.path, library.path)
            if rel is None:
                raise ValueError(f"Track is outside the library root: {track.path}")
            new_id = song_uuid(namespace, rel)
            if new_id in seen:
                raise ValueError("ReKey would create duplicate song IDs")
            seen.add(new_id)
            existing = self.db.get_track(new_id)
            if existing is not None and existing.id != track.id:
                raise ValueError("ReKey would collide with an existing track ID")
            planned.append((track, new_id))
        backup = Path(self.db.path).with_name(
            f"{Path(self.db.path).stem}.rekey-backup-{int(time.time())}.sqlite"
        )
        self.db.backup(backup)
        operation_id = self.db.create_operation(
            "rekey", f"ReKey {library.name} to {namespace}", undoable=False
        )
        updated = 0
        try:
            for track, new_id in planned:
                if new_id == track.id:
                    continue
                self.db.move_song(track.id, track.path, new_id)
                self.db.add_operation_item(
                    operation_id,
                    song_id=new_id,
                    path=track.path,
                    prior={"old_id": track.id, "new_id": new_id},
                    result={"namespace": namespace},
                )
                updated += 1
            self.db.set_library_namespace(library.id, namespace)
            self.db.finish_operation(operation_id)
        except Exception:
            self.db.finish_operation(operation_id, "failed")
            raise
        return RekeyResult(
            library_id=library.id,
            namespace=namespace,
            updated=updated,
            backup=str(backup),
        )

    def relocate_library(self, library_id: str, new_root: str | Path) -> Library:
        """Re-root a library after its folder has been moved, with a backup."""
        backup = Path(self.db.path).with_name(
            f"{Path(self.db.path).stem}.relocate-backup-{int(time.time())}.sqlite"
        )
        self.db.backup(backup)
        return self.db.relocate_library(library_id, new_root)

    def set_artwork(
        self,
        song_ids: Sequence[str],
        data: bytes,
        *,
        mime: str = "",
        progress: Progress | None = None,
    ) -> list[str]:
        try:
            normalized = normalize_artwork(
                data,
                max_size=self.artwork_max_size,
                quality=self.artwork_quality,
                aspect=self.artwork_aspect,
            )
        except ValueError as exc:
            return [str(exc)]
        errors: list[str] = []
        total = len(song_ids)
        for index, song_id in enumerate(song_ids, start=1):
            try:
                track = self.db.get_track(song_id)
                if track is None:
                    raise ValueError("Track not found")
                path = Path(track.path)
                stat_before = path.stat()
                remove_artwork(path)
                write_artwork(path, normalized, mime="image/jpeg")
                self._restore_mtime(path, stat_before)
                metadata = read_metadata(track.path)
                library = self.db.get_library(track.library_id or "")
                if library is None:
                    raise ValueError("Library not found")
                self.db.upsert_tracks([metadata], library)
            except Exception as exc:
                errors.append(f"{song_id}: {exc}")
            if progress:
                progress("Writing artwork", index, total, "")
        return errors

    def remove_artwork(self, song_ids: Sequence[str]) -> list[str]:
        errors: list[str] = []
        for song_id in song_ids:
            try:
                track = self.db.get_track(song_id)
                if track is None:
                    raise ValueError("Track not found")
                path = Path(track.path)
                stat_before = path.stat()
                remove_artwork(track.path)
                self._restore_mtime(path, stat_before)
                metadata = read_metadata(track.path)
                library = self.db.get_library(track.library_id or "")
                if library is None:
                    raise ValueError("Library not found")
                self.db.upsert_tracks([metadata], library)
            except Exception as exc:
                errors.append(f"{song_id}: {exc}")
        return errors

    def extract_artwork(self, song_id: str, destination: str | Path) -> Path:
        track = self.db.get_track(song_id)
        if track is None:
            raise ValueError("Track not found")
        metadata = read_metadata(track.path)
        if not metadata.artwork:
            raise ValueError("Track has no embedded artwork")
        artwork = metadata.artwork[0]
        suffix = ".png" if artwork.mime == "image/png" else ".jpg"
        path = Path(destination)
        if path.is_dir():
            path = path / f"{Path(track.path).stem}{suffix}"
        elif not path.suffix:
            path = path.with_suffix(suffix)
        path.write_bytes(artwork.data)
        return path

    # ------------------------------------------------------------------
    # Undo

    def undo_last(self) -> UndoResult | None:
        operation = self.db.latest_undoable_operation()
        if operation is None:
            return None
        items = self.db.get_operation_items(operation.id)
        undone = 0
        errors: list[str] = []
        try:
            for item in items:
                if item["error"]:
                    continue
                prior = json.loads(item["prior_json"]) if item["prior_json"] else {}
                result = json.loads(item["result_json"]) if item["result_json"] else {}
                if operation.kind == "import":
                    undone += self._undo_import_item(prior, result, errors)
                elif operation.kind == "tags":
                    undone += self._undo_tag_item(prior, errors)
                elif operation.kind == "organize":
                    undone += self._undo_organize_item(prior, errors)
                elif operation.kind == "delete":
                    undone += self._undo_delete_item(prior, errors)
            self.db.mark_operation_undone(operation.id, True)
            return UndoResult(
                operation_id=operation.id,
                kind=operation.kind,
                undone=undone,
                errors=errors,
            )
        except Exception as exc:
            errors.append(str(exc))
            return UndoResult(
                operation_id=operation.id,
                kind=operation.kind,
                undone=undone,
                errors=errors,
            )

    def redo_last(self) -> UndoResult | None:
        operation = self.db.latest_undone_operation()
        if operation is None:
            return None
        items = self.db.get_operation_items(operation.id)
        redone = 0
        errors: list[str] = []
        for item in items:
            if item["error"]:
                continue
            prior = json.loads(item["prior_json"]) if item["prior_json"] else {}
            result = json.loads(item["result_json"]) if item["result_json"] else {}
            try:
                if operation.kind == "tags":
                    redone += self._redo_tag_item(prior, result, errors)
                elif operation.kind == "organize":
                    redone += self._redo_organize_item(prior, errors)
                elif operation.kind == "import":
                    redone += self._redo_import_item(prior, result, errors)
                else:
                    errors.append(f"Redo is not supported for {operation.kind} operations")
            except Exception as exc:
                errors.append(str(exc))
        self.db.mark_operation_undone(operation.id, False)
        return UndoResult(
            operation_id=operation.id,
            kind=operation.kind,
            undone=redone,
            errors=errors,
        )

    def _redo_tag_item(
        self, prior: dict[str, Any], result: dict[str, Any], errors: list[str]
    ) -> int:
        path_value = str(prior.get("path", ""))
        tags_data = result.get("tags") or {}
        if not path_value or not tags_data or not Path(path_value).exists():
            errors.append(f"{path_value}: file is missing")
            return 0
        try:
            edits = dict(tags_data)
            edits.pop("custom", None)
            write_tags(path_value, edits)
            metadata = read_metadata(path_value)
            library_id = prior.get("library_id")
            library = self.db.get_library(library_id) if library_id else None
            if library is None:
                track = self.db.get_track_by_path(path_value)
                library = self.db.get_library(track.library_id or "") if track else None
            if library is None:
                return 0
            self.db.upsert_tracks([metadata], library)
            return 1
        except Exception as exc:
            errors.append(f"{path_value}: {exc}")
            return 0

    def _redo_organize_item(self, prior: dict[str, Any], errors: list[str]) -> int:
        old_path = Path(str(prior.get("old_path", "")))
        new_path = Path(str(prior.get("new_path", "")))
        if not old_path.exists() or new_path.exists():
            errors.append(f"{old_path}: cannot redo move")
            return 0
        try:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_path), str(new_path))
            self.db.move_song(str(prior["old_id"]), str(new_path), str(prior["new_id"]))
            return 1
        except Exception as exc:
            errors.append(f"{old_path}: {exc}")
            return 0

    def _redo_import_item(
        self, prior: dict[str, Any], result: dict[str, Any], errors: list[str]
    ) -> int:
        if prior.get("in_place"):
            return 0
        source = Path(str(prior.get("source", "")))
        destination = Path(str(prior.get("destination", "")))
        if not source.exists():
            errors.append(f"{source}: source no longer exists")
            return 0
        try:
            if destination.exists():
                errors.append(f"{destination}: destination already exists")
                return 0
            self._atomic_copy(source, destination)
            metadata = read_metadata(destination)
            library_id = prior.get("library_id")
            library = self.db.get_library(library_id) if library_id else None
            if library is None:
                track = self.db.get_track(str(result.get("track_id", "")))
                library = self.db.get_library(track.library_id or "") if track else None
            if library is None:
                return 0
            self.db.upsert_tracks([metadata], library)
            return 1
        except Exception as exc:
            errors.append(f"{source}: {exc}")
            return 0

    def _undo_import_item(
        self, prior: dict[str, Any], result: dict[str, Any], errors: list[str]
    ) -> int:
        source = Path(str(prior.get("source", "")))
        destination = Path(str(prior.get("destination", "")))
        mode = str(prior.get("mode", "copy"))
        in_place = bool(prior.get("in_place"))
        track_id = str(result.get("track_id", ""))
        try:
            if not in_place and destination.exists():
                if mode == "move" and not source.exists():
                    source.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(destination), str(source))
                elif mode == "copy":
                    destination.unlink()
            if track_id:
                self.db.delete_tracks([track_id])
            if in_place and prior.get("tags"):
                tags = TagSet(**prior["tags"])
                edits = tagset_to_dict(tags)
                edits.pop("custom", None)
                if destination.exists():
                    write_tags(destination, edits)
                    metadata = read_metadata(destination)
                    library_id = prior.get("library_id")
                    library = self.db.get_library(library_id) if library_id else None
                    if library is not None:
                        self.db.upsert_tracks([metadata], library)
            return 1
        except Exception as exc:
            errors.append(f"{destination}: {exc}")
            return 0

    def _undo_tag_item(self, prior: dict[str, Any], errors: list[str]) -> int:
        path_value = prior.get("path") or ""
        tags_data = prior.get("tags") or {}
        if not path_value or not tags_data:
            return 0
        try:
            path = Path(path_value)
            if not path.exists():
                raise FileNotFoundError(path_value)
            edits = dict(tags_data)
            edits.pop("custom", None)
            stat_before = path.stat()
            write_tags(path, edits)
            self._restore_mtime(path, stat_before)
            metadata = read_metadata(path)
            library_id = prior.get("library_id")
            library = self.db.get_library(library_id) if library_id else None
            if library is None:
                return 0
            self.db.upsert_tracks([metadata], library)
            return 1
        except Exception as exc:
            errors.append(f"{path_value}: {exc}")
            return 0

    def _undo_organize_item(self, prior: dict[str, Any], errors: list[str]) -> int:
        old_path = Path(str(prior.get("old_path", "")))
        new_path = Path(str(prior.get("new_path", "")))
        old_id = str(prior.get("old_id", ""))
        new_id = str(prior.get("new_id", ""))
        try:
            if new_path.exists() and not old_path.exists():
                old_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(new_path), str(old_path))
            self.db.move_song(new_id, str(old_path), old_id)
            return 1
        except Exception as exc:
            errors.append(f"{new_path}: {exc}")
            return 0

    def _undo_delete_item(self, prior: dict[str, Any], errors: list[str]) -> int:
        path = str(prior.get("path", ""))
        tags_data = prior.get("tags") or {}
        if not path or not Path(path).exists():
            errors.append(f"{path}: file is missing")
            return 0
        try:
            if tags_data:
                edits = dict(tags_data)
                edits.pop("custom", None)
                write_tags(path, edits)
            metadata = read_metadata(path)
            library_id = prior.get("library_id")
            library = self.db.get_library(library_id) if library_id else None
            if library is None:
                return 0
            self.db.upsert_tracks([metadata], library)
            return 1
        except Exception as exc:
            errors.append(f"{path}: {exc}")
            return 0
