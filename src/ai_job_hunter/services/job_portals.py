"""Job portals fetched alongside company boards, at most once per polling interval.

Portals aggregate many employers, so they are queried with filters (country,
keywords) rather than crawled. Each portal's last successful fetch is kept in
a small local state file so frequent scheduled runs respect the portal's
terms (Himalayas: data refreshes daily).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from ai_job_hunter.connectors.adzuna import AdzunaConnector, AdzunaConnectorError
from ai_job_hunter.connectors.himalayas import HimalayasConnector, HimalayasConnectorError
from ai_job_hunter.connectors.jobicy import JobicyConnector, JobicyConnectorError
from ai_job_hunter.connectors.remoteok import RemoteOKConnector, RemoteOKConnectorError
from ai_job_hunter.connectors.remotive import RemotiveConnector, RemotiveConnectorError
from ai_job_hunter.domain.normalized_job import NormalizedJob

DEFAULT_STATE_PATH = Path("data/local/portal-state.json")
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PortalSpec:
    name: str
    min_interval: timedelta
    build: Callable[[httpx.Client | None], object]
    errors: tuple[type[Exception], ...]


class _RemotiveSoftwareDev:
    """One Remotive request for the software-dev category (Remotive asks for few calls a day)."""

    def __init__(self, client: httpx.Client | None) -> None:
        self._client = client

    def fetch_jobs(self) -> list[NormalizedJob]:
        with RemotiveConnector(category="software-dev", client=self._client) as connector:
            return connector.fetch_jobs()


PORTALS: dict[str, PortalSpec] = {
    "himalayas": PortalSpec(
        name="himalayas",
        min_interval=timedelta(hours=20),
        build=lambda client: HimalayasConnector(client=client),
        errors=(HimalayasConnectorError,),
    ),
    # Adzuna: free tier is ~250 calls/day and each run makes up to 16; needs ADZUNA_APP_ID/KEY.
    "adzuna": PortalSpec(
        name="adzuna",
        min_interval=timedelta(hours=12),
        build=lambda client: AdzunaConnector.from_settings(client),
        errors=(AdzunaConnectorError,),
    ),
    "remoteok": PortalSpec(
        name="remoteok",
        min_interval=timedelta(hours=4),
        build=lambda client: RemoteOKConnector(client=client),
        errors=(RemoteOKConnectorError,),
    ),
    "remotive": PortalSpec(
        name="remotive",
        min_interval=timedelta(hours=6),
        build=lambda client: _RemotiveSoftwareDev(client),
        errors=(RemotiveConnectorError,),
    ),
    "jobicy": PortalSpec(
        name="jobicy",
        min_interval=timedelta(hours=4),
        build=lambda client: JobicyConnector(client=client),
        errors=(JobicyConnectorError,),
    ),
}


@dataclass(frozen=True, slots=True)
class PortalFailure:
    portal: str
    error_type: str


def parse_portal_names(value: str | Sequence[str] | None) -> tuple[str, ...]:
    """Validate a comma-separated (or listed) portal selection."""

    if value is None:
        return ()
    items = value.split(",") if isinstance(value, str) else list(value)
    names = tuple(dict.fromkeys(item.strip().casefold() for item in items if item and item.strip()))
    unknown = [name for name in names if name not in PORTALS]
    if unknown:
        raise ValueError("Unknown job portal(s): " + ", ".join(unknown) + ". Known: " + ", ".join(PORTALS))
    return names


def due_portals(names: Sequence[str], *, state_path: Path = DEFAULT_STATE_PATH, now: datetime | None = None) -> list[str]:
    moment = now or datetime.now(UTC)
    state = _load_state(state_path)
    due = []
    for name in names:
        last = state.get(name)
        if last is None or moment - last >= PORTALS[name].min_interval:
            due.append(name)
    return due


def fetch_portals(
    names: Sequence[str],
    *,
    client: httpx.Client | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    record: bool = True,
    now: datetime | None = None,
) -> tuple[list[NormalizedJob], list[PortalFailure]]:
    """Fetch the given portals; on success remember the time (unless ``record`` is False)."""

    moment = now or datetime.now(UTC)
    offers: list[NormalizedJob] = []
    failures: list[PortalFailure] = []
    state = _load_state(state_path)
    for name in names:
        spec = PORTALS[name]
        try:
            fetched = spec.build(client).fetch_jobs()  # type: ignore[attr-defined]
        except spec.errors as error:
            # Portal error messages are safe by construction (status/type only, no credentials).
            LOGGER.warning("Portal %s skipped: %s", name, error)
            failures.append(PortalFailure(name, type(error).__name__))
            continue
        offers.extend(fetched)
        state[name] = moment
    if record:
        _save_state(state_path, state)
    return offers, failures


def _load_state(path: Path) -> dict[str, datetime]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    state: dict[str, datetime] = {}
    if isinstance(raw, dict):
        for name, value in raw.items():
            try:
                parsed = datetime.fromisoformat(value)
            except (TypeError, ValueError):
                continue
            state[name] = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return state


def _save_state(path: Path, state: dict[str, datetime]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps({name: value.isoformat() for name, value in state.items()}), encoding="utf-8")
    os.replace(temporary, path)
