"""Validated local configuration for employer-hosted job boards."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class JobSourceSpec(BaseModel):
    """One public ATS site, identified by the slug shown in its hosted URL."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    provider: str
    identifier: str = Field(min_length=1, max_length=255)
    company_name: str | None = Field(default=None, min_length=1, max_length=255)
    region: str | None = None
    max_jobs: int | None = Field(default=None, ge=1, le=10000)

    @field_validator("provider", mode="before")
    @classmethod
    def supported_provider(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip().casefold()
            if normalized in {
                "greenhouse", "lever", "ashby", "teamtailor", "smartrecruiters", "workable", "personio", "workday",
                "factorial",
            }:
                return normalized
        raise ValueError(
            "provider must be one of: greenhouse, lever, ashby, teamtailor, smartrecruiters, workable, personio, workday, factorial"
        )

    @field_validator("identifier")
    @classmethod
    def identifier_is_not_whitespace(cls, value: str) -> str:
        if not value:
            raise ValueError("identifier must not be empty")
        return value

    @field_validator("region", mode="before")
    @classmethod
    def normalize_region(cls, value: Any) -> Any:
        return value.strip().casefold() if isinstance(value, str) else value

    @model_validator(mode="after")
    def provider_options_are_valid(self) -> JobSourceSpec:
        if self.provider == "workday":
            from ai_job_hunter.connectors.workday import WORKDAY_REGION, split_workday_identifier

            split_workday_identifier(self.identifier)
            if self.region is None or not WORKDAY_REGION.fullmatch(self.region):
                raise ValueError("Workday region must be a data-centre label such as 'wd3'")
            return self
        if self.provider in {"greenhouse", "ashby", "teamtailor", "smartrecruiters", "workable"} and self.region is not None:
            raise ValueError("region is only supported by Lever, Personio, Factorial and Workday sources")
        if self.provider == "lever" and self.region not in {None, "global", "eu"}:
            raise ValueError("Lever region must be 'global' or 'eu'")
        if self.provider == "personio" and self.region not in {None, "de", "com"}:
            raise ValueError("Personio region must be 'de' or 'com'")
        if self.provider == "factorial" and self.region not in {None, "com", "es"}:
            raise ValueError("Factorial region must be 'com' or 'es'")
        return self


class JobSourcesConfig(BaseModel):
    """A non-empty list of employer job boards to query."""

    model_config = ConfigDict(extra="forbid")

    sources: list[JobSourceSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def sources_are_unique(self) -> JobSourcesConfig:
        keys = [
            (source.provider, source.identifier.casefold(), source.region)
            for source in self.sources
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("sources must not contain a duplicate provider and identifier")
        return self


class JobSourcesConfigError(ValueError):
    """A readable error for missing, malformed or invalid ATS configuration."""


def load_job_sources(path: str | Path) -> JobSourcesConfig:
    """Load and validate a UTF-8 JSON list of public ATS boards."""

    config_path = Path(path)
    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError as error:
        raise JobSourcesConfigError(
            f"Cannot read job sources config '{config_path}': {error}"
        ) from error
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise JobSourcesConfigError(
            f"Job sources config '{config_path}' is not valid JSON at line {error.lineno}, "
            f"column {error.colno}: {error.msg}"
        ) from error
    try:
        return JobSourcesConfig.model_validate(payload)
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc']) or '<root>'}: {item['msg']}"
            for item in error.errors()
        )
        raise JobSourcesConfigError(
            f"Invalid job sources config '{config_path}': {details}"
        ) from error
