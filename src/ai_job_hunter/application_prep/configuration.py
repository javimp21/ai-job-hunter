"""Optional local writing-style and document metadata; files are never uploaded."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ai_job_hunter.application_prep.models import CandidateDocument, CandidateWritingStyle


DEFAULT_WRITING_STYLE_PATH = Path("candidate_writing.local.json")
DEFAULT_DOCUMENTS_PATH = Path("candidate_documents.local.json")
DEFAULT_APPLICATION_FACTS_PATH = Path("candidate_application.local.json")


class CandidateDocumentsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    documents: tuple[CandidateDocument, ...] = ()


class CandidateApplicationFacts(BaseModel):
    """Explicit private contact facts used only for factual form fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=80)
    linkedin_url: str | None = Field(default=None, max_length=2048)
    github_url: str | None = Field(default=None, max_length=2048)
    portfolio_url: str | None = Field(default=None, max_length=2048)

    @field_validator("first_name", "last_name", "email", "phone", "linkedin_url", "github_url", "portfolio_url", mode="before")
    @classmethod
    def blank_values_are_missing(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is not None and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value) is None:
            raise ValueError("email must be a valid address")
        return value

    @field_validator("linkedin_url", "github_url", "portfolio_url")
    @classmethod
    def validate_public_profile_urls(cls, value: str | None) -> str | None:
        if value is None:
            return value
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if (
            parsed.scheme.casefold() != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("profile links must be absolute HTTPS URLs without credentials")
        return value


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


def load_candidate_application_facts(path: str | Path | None = None) -> CandidateApplicationFacts:
    """Load optional factual contact fields; absent values remain unavailable."""

    config_path = Path(path) if path is not None else DEFAULT_APPLICATION_FACTS_PATH
    payload = _read_json(config_path, missing_default={})
    return _validate(CandidateApplicationFacts, payload, config_path)


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
