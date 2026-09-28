"""Atomic persistence for ignored, private browser-assisted application sessions."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from pydantic import ValidationError

from ai_job_hunter.application_prep.browser.models import ApplicationSession


DEFAULT_SESSIONS_PATH = Path("data/local/application-sessions.local.json")


class ApplicationSessionStoreError(ValueError):
    """Safe local session store error; never includes stored answers or field values."""


class ApplicationSessionStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_SESSIONS_PATH

    def list(self) -> list[ApplicationSession]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ApplicationSessionStoreError(
                f"Cannot read private application sessions ({type(error).__name__})."
            ) from error
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ApplicationSessionStoreError("Private application sessions have an unsupported format.")
        records = payload.get("sessions")
        if not isinstance(records, list):
            raise ApplicationSessionStoreError("Private application sessions have invalid record data.")
        try:
            return [ApplicationSession.model_validate(item) for item in records]
        except ValidationError as error:
            fields = "; ".join(".".join(str(part) for part in item["loc"]) for item in error.errors())
            raise ApplicationSessionStoreError(f"Private application session validation failed in: {fields}.") from error

    def get_by_job(self, job_id: UUID) -> ApplicationSession | None:
        return next((item for item in self.list() if item.job_id == job_id), None)

    def save(self, session: ApplicationSession) -> None:
        sessions = self.list()
        for index, existing in enumerate(sessions):
            if existing.job_id == session.job_id:
                sessions[index] = session
                break
        else:
            sessions.append(session)
        self._write(sessions)

    def _write(self, sessions: list[ApplicationSession]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "sessions": [item.model_dump(mode="json") for item in sessions]}
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                "w", encoding="utf-8", newline="\n", dir=self.path.parent,
                prefix=f".{self.path.name}.", suffix=".tmp", delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError as error:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise ApplicationSessionStoreError(
                f"Cannot save private application sessions ({type(error).__name__})."
            ) from error
