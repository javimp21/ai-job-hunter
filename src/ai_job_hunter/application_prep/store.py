"""Atomic JSON persistence for private local application packages."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from pydantic import ValidationError

from ai_job_hunter.application_prep.models import ApplicationPackage


DEFAULT_PACKAGES_PATH = Path("data/local/application-packages.local.json")


class ApplicationPackageStoreError(ValueError):
    """Safe store error that never includes package answer contents."""


class ApplicationPackageStore:
    """Read/write only the ignored local package JSON store."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PACKAGES_PATH

    def list(self) -> list[ApplicationPackage]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ApplicationPackageStoreError(
                f"Cannot read local application packages '{self.path}' ({type(error).__name__})."
            ) from error
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ApplicationPackageStoreError(
                f"Local application package store '{self.path}' has an unsupported format."
            )
        packages = payload.get("packages")
        if not isinstance(packages, list):
            raise ApplicationPackageStoreError(
                f"Local application package store '{self.path}' has invalid package data."
            )
        try:
            return [ApplicationPackage.model_validate(item) for item in packages]
        except ValidationError as error:
            fields = "; ".join(
                ".".join(str(part) for part in item["loc"])
                for item in error.errors()
            )
            raise ApplicationPackageStoreError(
                f"Local application package store '{self.path}' failed validation in: {fields}."
            ) from error

    def get_by_job(self, job_id: UUID) -> ApplicationPackage | None:
        return next((item for item in self.list() if item.job_id == job_id), None)

    def save(self, package: ApplicationPackage) -> None:
        packages = self.list()
        replaced = False
        for index, existing in enumerate(packages):
            if existing.job_id == package.job_id:
                packages[index] = package
                replaced = True
                break
        if not replaced:
            packages.append(package)
        self._write(packages)

    def _write(self, packages: list[ApplicationPackage]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "packages": [item.model_dump(mode="json") for item in packages],
        }
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                "w", encoding="utf-8", newline="\n", dir=self.path.parent,
                prefix=f".{self.path.name}.", suffix=".tmp", delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        except OSError as error:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise ApplicationPackageStoreError(
                f"Cannot save local application packages '{self.path}' ({type(error).__name__})."
            ) from error
