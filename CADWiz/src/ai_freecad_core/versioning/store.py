# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Atomic filesystem-backed protected versions with manifests and recovery journal."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from ai_freecad_core.execution.contracts import Command

from .contracts import DocumentVersionId, ProtectedVersion


class DocumentCopySource(Protocol):
    """Native adapter port that writes and restores document copies."""

    def write_copy(self, command: Command, destination: Path) -> None: ...

    def restore_copy(self, source: Path, document_id: str) -> None: ...


class RecoveryIssueCode(str, Enum):
    """Stable recovery issue codes without coupling callers to filesystem errors."""

    TEMPORARY_ARTIFACT = "temporary_artifact"
    MISSING_COPY = "missing_copy"
    HASH_MISMATCH = "hash_mismatch"
    ORPHAN_COPY = "orphan_copy"


@dataclass(frozen=True, slots=True)
class RecoveryIssue:
    """Immutable code/path pair discovered during startup inspection."""

    code: RecoveryIssueCode
    path: str


class FilesystemVersionStore:
    """Persist protected copies atomically beneath one configured root."""

    def __init__(
        self,
        root: Path,
        source: DocumentCopySource,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._root = root.resolve()
        self._source = source
        self._id_factory = id_factory or (lambda: uuid4().hex)
        self._clock = clock or (lambda: datetime.now(UTC))

    def create_protected_version(self, command: Command) -> ProtectedVersion:
        """Write, hash, publish, manifest, and journal a protected document copy."""
        version_id = DocumentVersionId(self._id_factory())
        directory = self._document_directory(command.target.document_id)
        directory.mkdir(parents=True, exist_ok=True)
        final = directory / f"{version_id.value}.FCStd"
        # FreeCAD's serializer requires FCStd to remain the final suffix.
        temporary = directory / f".{version_id.value}.tmp.FCStd"
        manifest = directory / f"{version_id.value}.json"
        manifest_temporary = directory / f".{version_id.value}.json.tmp"
        if final.exists() or manifest.exists():
            raise FileExistsError(f"Protected version already exists: {version_id.value}")
        try:
            self._source.write_copy(command, temporary)
            self._sync_file(temporary)
            content_hash = self._hash(temporary)
            os.replace(temporary, final)
            payload = {
                "version_id": version_id.value,
                "document_id": command.target.document_id,
                "source_model_revision": command.target.expected_model_revision,
                "command_id": command.identifier,
                "content_hash": content_hash,
                "storage_location": str(final),
                "created_at": self._clock().astimezone(UTC).isoformat(),
            }
            self._write_json_atomic(manifest_temporary, manifest, payload)
            self._journal("created", payload)
            return ProtectedVersion(
                version_id,
                command.target.document_id,
                command.target.expected_model_revision,
                content_hash,
                str(final),
            )
        except Exception:
            temporary.unlink(missing_ok=True)
            manifest_temporary.unlink(missing_ok=True)
            raise

    def restore(self, version: ProtectedVersion) -> None:
        """Verify content before delegating restoration to the native adapter."""
        source = self._checked_storage_path(version.storage_location)
        if not source.is_file():
            raise FileNotFoundError(f"Protected version is missing: {version.version_id.value}")
        actual = self._hash(source)
        if actual != version.content_hash:
            raise ValueError(f"Protected version hash mismatch: {version.version_id.value}")
        self._source.restore_copy(source, version.document_id)
        self._journal(
            "restored",
            {"version_id": version.version_id.value, "document_id": version.document_id},
        )

    def list_versions(self, document_id: str) -> tuple[ProtectedVersion, ...]:
        """Load valid manifests in creation order without trusting filenames."""
        directory = self._document_directory(document_id)
        if not directory.exists():
            return ()
        found: list[tuple[str, ProtectedVersion]] = []
        for path in sorted(directory.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("document_id") != document_id:
                continue
            version = ProtectedVersion(
                DocumentVersionId(payload["version_id"]),
                payload["document_id"],
                int(payload["source_model_revision"]),
                payload["content_hash"],
                payload["storage_location"],
            )
            found.append((payload["created_at"], version))
        return tuple(
            item[1] for item in sorted(found, key=lambda item: (item[0], item[1].version_id.value))
        )

    def prune(self, document_id: str, keep: int) -> tuple[DocumentVersionId, ...]:
        """Remove oldest versions while retaining at least ``keep`` newest copies."""
        if keep < 1:
            raise ValueError("retention count must be positive")
        versions = self.list_versions(document_id)
        removed: list[DocumentVersionId] = []
        for version in versions[:-keep]:
            storage = self._checked_storage_path(version.storage_location)
            manifest = storage.with_suffix(".json")
            storage.unlink(missing_ok=True)
            manifest.unlink(missing_ok=True)
            removed.append(version.version_id)
            self._journal(
                "pruned",
                {"version_id": version.version_id.value, "document_id": document_id},
            )
        return tuple(removed)

    def inspect_recovery(self) -> tuple[RecoveryIssue, ...]:
        """Inspect interrupted writes and manifest integrity without changing files."""
        if not self._root.exists():
            return ()
        issues: list[RecoveryIssue] = []
        temporary_paths = set(self._root.rglob("*.tmp"))
        temporary_paths.update(self._root.rglob("*.tmp.FCStd"))
        for path in sorted(temporary_paths):
            issues.append(RecoveryIssue(RecoveryIssueCode.TEMPORARY_ARTIFACT, str(path)))
        for directory in (
            sorted((self._root / "documents").glob("*"))
            if (self._root / "documents").exists()
            else ()
        ):
            for manifest in sorted(directory.glob("*.json")):
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                storage = self._checked_storage_path(payload["storage_location"])
                if not storage.is_file():
                    issues.append(RecoveryIssue(RecoveryIssueCode.MISSING_COPY, str(storage)))
                elif self._hash(storage) != payload["content_hash"]:
                    issues.append(RecoveryIssue(RecoveryIssueCode.HASH_MISMATCH, str(storage)))
            manifested = {path.stem for path in directory.glob("*.json")}
            for storage in sorted(directory.glob("*.FCStd")):
                if storage.stem not in manifested:
                    issues.append(RecoveryIssue(RecoveryIssueCode.ORPHAN_COPY, str(storage)))
        return tuple(sorted(issues, key=lambda item: (item.code, item.path)))

    def clean_temporary_artifacts(self) -> tuple[str, ...]:
        """Remove only interrupted temporary artifacts beneath the configured root."""
        removed = []
        for issue in self.inspect_recovery():
            if issue.code == RecoveryIssueCode.TEMPORARY_ARTIFACT:
                path = self._checked_storage_path(issue.path)
                path.unlink(missing_ok=True)
                removed.append(str(path))
                self._journal("temporary_removed", {"path": str(path)})
        return tuple(removed)

    def _document_directory(self, document_id: str) -> Path:
        key = hashlib.sha256(document_id.encode("utf-8")).hexdigest()[:24]
        return self._root / "documents" / key

    def _checked_storage_path(self, value: str) -> Path:
        path = Path(value).resolve()
        if self._root not in path.parents:
            raise ValueError("Protected version path escapes version-store root")
        return path

    def _journal(self, event: str, payload: dict[str, object]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        record = {
            "event": event,
            "recorded_at": self._clock().astimezone(UTC).isoformat(),
            **payload,
        }
        with (self._root / "recovery.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return "sha256:" + digest.hexdigest()

    @staticmethod
    def _sync_file(path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError("Native copy source did not create a file")
        with path.open("r+b") as stream:
            os.fsync(stream.fileno())

    @staticmethod
    def _write_json_atomic(temporary: Path, final: Path, payload: dict[str, object]) -> None:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, final)
