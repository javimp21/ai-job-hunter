"""Local state that keeps recurring lead imports idempotent and polite.

Monthly sources (Hacker News "Who is hiring?", the public company
directories) are checked by the daily maintenance run, but only import when
there is something new. The state lives in a small local JSON file next to the
other runtime state; losing it only means one redundant (deduplicated) import.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULT_STATE_PATH = Path("data/local/lead-import-state.json")
# Comments keep arriving for days after a thread opens, so a thread is only
# final once it was imported this long after it was posted.
HN_SETTLE_AFTER = timedelta(days=7)
DIRECTORY_REIMPORT_AFTER = timedelta(days=30)
# The directories are two small README downloads; look at most weekly.
DIRECTORY_CHECK_EVERY = timedelta(days=7)


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_state(state: Mapping[str, Any], path: Path = DEFAULT_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def hn_thread_needs_import(
    thread_id: str, posted_at: datetime | None, state: Mapping[str, Any], *, now: datetime | None = None
) -> bool:
    """True unless the thread was already imported after it had settled."""

    entry = (state.get("hn_threads") or {}).get(str(thread_id))
    imported_at = _parse(entry.get("imported_at")) if isinstance(entry, Mapping) else None
    if imported_at is None:
        return True
    if posted_at is None:
        return False
    return imported_at - posted_at < HN_SETTLE_AFTER


def record_hn_thread(state: dict[str, Any], thread_id: str, *, now: datetime | None = None) -> None:
    threads = state.setdefault("hn_threads", {})
    threads[str(thread_id)] = {"imported_at": (now or datetime.now(UTC)).isoformat()}


def directories_check_due(provider_names: list[str], state: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    """False while every directory was checked within the check interval."""

    moment = now or datetime.now(UTC)
    entries = state.get("directories") or {}
    for name in provider_names:
        entry = entries.get(name)
        checked = _parse(entry.get("checked_at")) if isinstance(entry, Mapping) else None
        if checked is None or moment - checked >= DIRECTORY_CHECK_EVERY:
            return True
    return False


def directory_needs_import(provider: str, body_sha256: str, state: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    """Import when the source content changed or the last import is 30+ days old."""

    moment = now or datetime.now(UTC)
    entry = (state.get("directories") or {}).get(provider)
    if not isinstance(entry, Mapping):
        return True
    imported = _parse(entry.get("imported_at"))
    if imported is None or entry.get("sha256") != body_sha256:
        return True
    return moment - imported >= DIRECTORY_REIMPORT_AFTER


def record_directory(
    state: dict[str, Any], provider: str, body_sha256: str, *, imported: bool, now: datetime | None = None
) -> None:
    moment = (now or datetime.now(UTC)).isoformat()
    entry = state.setdefault("directories", {}).setdefault(provider, {})
    entry["checked_at"] = moment
    if imported:
        entry["imported_at"] = moment
        entry["sha256"] = body_sha256


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
