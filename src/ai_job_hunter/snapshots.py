"""Private, validated snapshots of normalized Remotive offers."""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from ai_job_hunter.domain.normalized_job import NormalizedJob

SNAPSHOT_FORMAT = "ai-job-hunter.remotive-snapshot"
SNAPSHOT_VERSION = 1
JOB_SNAPSHOT_FORMAT = "ai-job-hunter.job-snapshot"
JOB_SNAPSHOT_VERSION = 1


class RemotiveSnapshotError(ValueError):
    """A snapshot could not be read, validated, or written."""


class RemotiveSnapshot(BaseModel):
    """Versioned local copy of the normalized Remotive response."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["ai-job-hunter.remotive-snapshot"]
    version: Literal[1]
    captured_at: datetime
    offers: list[NormalizedJob]

    @field_validator("captured_at")
    @classmethod
    def captured_at_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must include a timezone")
        return value

    @field_validator("offers")
    @classmethod
    def offers_are_from_remotive(cls, values: list[NormalizedJob]) -> list[NormalizedJob]:
        if any(offer.provider != "remotive" for offer in values):
            raise ValueError("all offers must have provider 'remotive'")
        return values


class JobSnapshot(BaseModel):
    """Versioned normalized snapshot that can contain several providers."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["ai-job-hunter.job-snapshot"]
    version: Literal[1]
    captured_at: datetime
    offers: list[NormalizedJob]

    @field_validator("captured_at")
    @classmethod
    def captured_at_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must include a timezone")
        return value


class JobSnapshotError(ValueError):
    """A multi-source or legacy snapshot could not be read or written."""


def save_remotive_snapshot(
    path: str | Path,
    offers: list[NormalizedJob],
) -> Path:
    """Write a normalized snapshot using an atomic UTF-8 replacement."""

    target = Path(path)
    try:
        snapshot = RemotiveSnapshot(
            format=SNAPSHOT_FORMAT,
            version=SNAPSHOT_VERSION,
            captured_at=datetime.now(UTC),
            offers=offers,
        )
        serialized = json.dumps(
            snapshot.model_dump(mode="json"),
            ensure_ascii=True,
            indent=2,
        ) + "\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(serialized)
            temporary_path.replace(target)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
    except (OSError, TypeError, ValueError, ValidationError) as error:
        raise RemotiveSnapshotError(
            f"Could not save Remotive snapshot '{target}': {error}"
        ) from error
    return target


def load_remotive_snapshot(path: str | Path) -> list[NormalizedJob]:
    """Read and validate a saved Remotive snapshot without network access."""

    snapshot_path = Path(path)
    try:
        raw = snapshot_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise RemotiveSnapshotError(
            f"Remotive snapshot '{snapshot_path}' is not valid UTF-8."
        ) from error
    except OSError as error:
        raise RemotiveSnapshotError(
            f"Cannot read Remotive snapshot '{snapshot_path}': {error}"
        ) from error
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RemotiveSnapshotError(
            f"Remotive snapshot '{snapshot_path}' is not valid JSON at line "
            f"{error.lineno}, column {error.colno}: {error.msg}"
        ) from error
    try:
        snapshot = RemotiveSnapshot.model_validate(payload)
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc']) or '<root>'}: {item['msg']}"
            for item in error.errors()
        )
        raise RemotiveSnapshotError(
            f"Invalid Remotive snapshot '{snapshot_path}': {details}"
        ) from error
    return snapshot.offers


def save_job_snapshot(path: str | Path, offers: list[NormalizedJob]) -> Path:
    """Atomically save normalized offers from one or more public providers."""

    target = Path(path)
    try:
        snapshot = JobSnapshot(
            format=JOB_SNAPSHOT_FORMAT,
            version=JOB_SNAPSHOT_VERSION,
            captured_at=datetime.now(UTC),
            offers=offers,
        )
        serialized = json.dumps(
            snapshot.model_dump(mode="json"), ensure_ascii=True, indent=2
        ) + "\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(serialized)
            temporary_path.replace(target)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
    except (OSError, TypeError, ValueError, ValidationError) as error:
        raise JobSnapshotError(f"Could not save job snapshot '{target}': {error}") from error
    return target


def load_job_snapshot(path: str | Path) -> list[NormalizedJob]:
    """Load a mixed-provider snapshot or the earlier Remotive-only format offline."""

    snapshot_path = Path(path)
    try:
        raw = snapshot_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise JobSnapshotError(f"Job snapshot '{snapshot_path}' is not valid UTF-8.") from error
    except OSError as error:
        raise JobSnapshotError(f"Cannot read job snapshot '{snapshot_path}': {error}") from error
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise JobSnapshotError(
            f"Job snapshot '{snapshot_path}' is not valid JSON at line {error.lineno}, "
            f"column {error.colno}: {error.msg}"
        ) from error
    if isinstance(payload, dict) and payload.get("format") == SNAPSHOT_FORMAT:
        try:
            return load_remotive_snapshot(snapshot_path)
        except RemotiveSnapshotError as error:
            raise JobSnapshotError(str(error)) from error
    try:
        snapshot = JobSnapshot.model_validate(payload)
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc']) or '<root>'}: {item['msg']}"
            for item in error.errors()
        )
        raise JobSnapshotError(f"Invalid job snapshot '{snapshot_path}': {details}") from error
    return snapshot.offers
