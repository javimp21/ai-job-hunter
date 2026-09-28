"""Optional local writing-style and document metadata; files are never uploaded."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from ai_job_hunter.application_prep.models import CandidateDocument, CandidateWritingStyle


DEFAULT_WRITING_STYLE_PATH = Path("candidate_writing.local.json")
DEFAULT_DOCUMENTS_PATH = Path("candidate_documents.local.json")


class CandidateDocumentsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    documents: tuple[CandidateDocument, ...] = ()


class ApplicationPreparationConfigError(ValueError):
    """Safe, value-free configuration error for local application-prep files."""


def load_candidate_writing_style(path: str | Path | None = None) -> CandidateWritingStyle:
    """Load optional style preferences; absent config uses concise factual defaults."""

    config_path = Path(path) if path is not None else DEFAULT_WRITING_STYLE_PATH
    payload = _read_json(config_path, missing_default={})
    return _validate(CandidateWritingStyle, payload, config_path)


def load_candidate_documents(path: str | Path | None = None) -> CandidateDocumentsConfig:
    """Load document metadata without reading, copying, or modifying any file."""

    config_path = Path(path) if path is not None else DEFAULT_DOCUMENTS_PATH
    payload = _read_json(config_path, missing_default={"documents": []})
    if isinstance(payload, list):
        payload = {"documents": payload}
    return _validate(CandidateDocumentsConfig, payload, config_path)


def _read_json(path: Path, *, missing_default: Any) -> Any:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return missing_default
    except OSError as error:
        raise ApplicationPreparationConfigError(
            f"Cannot read application preparation config '{path}' ({type(error).__name__})."
        ) from error
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise ApplicationPreparationConfigError(
            f"Application preparation config '{path}' is invalid JSON at "
            f"line {error.lineno}, column {error.colno}."
        ) from error


def _validate(model: type[BaseModel], payload: Any, path: Path) -> Any:
    try:
        return model.model_validate(payload)
    except ValidationError as error:
        locations = "; ".join(
            f"{'.'.join(str(part) for part in item['loc']) or '<root>'}: {item['msg']}"
            for item in error.errors()
        )
        # Do not include rejected input values; local configuration may contain
        # names and paths that should not appear in logs or terminal errors.
        raise ApplicationPreparationConfigError(
            f"Invalid application preparation config '{path}': {locations}"
        ) from error
