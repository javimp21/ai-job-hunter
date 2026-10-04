"""Manfred (getmanfred.com) Spanish tech-jobs portal.

Uses the public, keyless JSON that Manfred's own site reads. It is not a
documented API, so every shape assumption is checked and a change raises
``ManfredConnectorError`` instead of ingesting guesses. The list endpoint
returns every offer ever published (mostly CLOSED); only ``ACTIVE`` ones are
kept, and each active offer's detail endpoint supplies the description.
Manfred's robots.txt allows crawling; callers throttle to once per hour.
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

import httpx

from ai_job_hunter.domain.normalized_job import (
    EmploymentType,
    NormalizedJob,
    RemotePolicy,
    SalaryPeriod,
)

LIST_URL = "https://www.getmanfred.com/api/v2/public/offers"
OFFER_URL = "https://www.getmanfred.com/ofertas-empleo/{id}/{slug}"
MANFRED_USER_AGENT = "AI-Job-Hunter/0.1 (personal job discovery)"
_MAX_LIST_BYTES = 16 * 1024 * 1024
_MAX_DETAIL_BYTES = 2 * 1024 * 1024
_DETAIL_PAUSE_SECONDS = 0.5
_CURRENCIES = {"€": "EUR", "US$": "USD", "£": "GBP", "MXN$": "MXN"}
# Detail fields that hold the offer text, in reading order, with their headings.
_DESCRIPTION_SECTIONS = (
    ("introduction", None),
    ("whatWillYouDo", "Qué harás"),
    ("responsibilities", "Responsabilidades"),
    ("whatTheyAskFor", "Qué piden"),
    ("whereWillDoIt", "Dónde"),
    ("whenWillDoIt", "Cuándo"),
    ("whatOffering", "Qué ofrecen"),
)


class ManfredConnectorError(RuntimeError):
    """A safe, user-readable portal failure (status or shape only)."""


class ManfredConnector:
    provider = "manfred"

    def __init__(
        self,
        *,
        max_offers: int = 100,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
        detail_pause: float = _DETAIL_PAUSE_SECONDS,
    ) -> None:
        if max_offers < 1:
            raise ValueError("max_offers must be positive")
        self.max_offers = max_offers
        self._client = client
        self._timeout = timeout
        self._detail_pause = detail_pause

    def fetch_jobs(self) -> list[NormalizedJob]:
        client = self._client or httpx.Client(timeout=self._timeout, headers={"User-Agent": MANFRED_USER_AGENT})
        discovered_at = datetime.now(UTC)
        try:
            listing = self._get_json(client, LIST_URL, _MAX_LIST_BYTES)
            if not isinstance(listing, list):
                raise ManfredConnectorError("Manfred returned an unexpected payload (expected a list).")
            if listing and not any(isinstance(raw, Mapping) and "status" in raw and "id" in raw for raw in listing):
                raise ManfredConnectorError("Manfred offers no longer match the expected fields.")
            active = [raw for raw in listing if isinstance(raw, Mapping) and raw.get("status") == "ACTIVE"]
            jobs: list[NormalizedJob] = []
            for index, raw in enumerate(active[: self.max_offers]):
                detail: Mapping[str, Any] | None = None
                if index and self._detail_pause:
                    time.sleep(self._detail_pause)
                try:
                    payload = self._get_json(client, f"{LIST_URL}/{int(raw['id'])}", _MAX_DETAIL_BYTES)
                    detail = payload if isinstance(payload, Mapping) else None
                except (ManfredConnectorError, KeyError, TypeError, ValueError):
                    detail = None  # keep the offer without a description
                try:
                    jobs.append(_normalize_job(raw, detail, discovered_at=discovered_at))
                except (KeyError, TypeError, ValueError):
                    continue
            if active and not jobs:
                raise ManfredConnectorError("Manfred offers no longer match the expected fields.")
            return jobs
        finally:
            if self._client is None:
                client.close()

    def _get_json(self, client: httpx.Client, url: str, limit: int) -> Any:
        try:
            response = client.get(url, params={"lang": "ES"}, timeout=self._timeout)
        except httpx.HTTPError as error:
            raise ManfredConnectorError(f"Manfred request failed ({type(error).__name__}).") from None
        if response.status_code != 200:
            raise ManfredConnectorError(f"Manfred returned HTTP {response.status_code}.")
        if len(response.content) > limit:
            raise ManfredConnectorError("Manfred response is too large.")
        try:
            return response.json()
        except ValueError:
            raise ManfredConnectorError("Manfred returned invalid JSON.") from None


def _normalize_job(
    raw: Mapping[str, Any], detail: Mapping[str, Any] | None, *, discovered_at: datetime
) -> NormalizedJob:
    offer_id = raw["id"]
    slug = _text(raw.get("slug"))
    title = _text(raw.get("position"))
    if isinstance(offer_id, bool) or not isinstance(offer_id, int) or not slug or not title:
        raise ValueError("id, slug and position are required")
    url = OFFER_URL.format(id=offer_id, slug=slug)
    company = raw.get("company")
    company = company if isinstance(company, Mapping) else {}
    salary_min = _amount(raw.get("salaryFrom"))
    salary_max = _amount(raw.get("salaryTo"))
    if salary_min is not None and salary_max is not None and salary_min > salary_max:
        salary_min = salary_max = None
    currency = _CURRENCIES.get((_text(raw.get("currency")) or "").replace(" ", ""))
    has_salary = currency is not None and (salary_min is not None or salary_max is not None)
    locations = [item.strip() for item in raw.get("locations") or [] if isinstance(item, str) and item.strip()]
    location = "; ".join(locations)[:255] or None
    employment = EmploymentType.CONTRACT if raw.get("isFreelance") is True else None
    working_day = detail.get("workingDayInfo") if detail else None
    if employment is None and isinstance(working_day, Mapping) and working_day.get("isFullTime") is True:
        employment = EmploymentType.FULL_TIME
    return NormalizedJob(
        provider=ManfredConnector.provider,
        external_id=str(offer_id),
        source_url=url,
        canonical_url=url,
        apply_url=url,
        title=title,
        company_name=_text(company.get("name")),
        company_website=_text(company.get("web")),
        description=_description(detail),
        location=location,
        remote_policy=_remote_policy(raw.get("remotePercentage")),
        salary_min=salary_min if has_salary else None,
        salary_max=salary_max if has_salary else None,
        currency=currency if has_salary else None,
        # Manfred publishes gross annual salaries (observed 35,000-168,000).
        salary_period=SalaryPeriod.YEAR if has_salary else None,
        employment_type=employment,
        # `updatedAt` is the last edit; `lastStatusChange` (detail) is when the
        # offer last became ACTIVE, the closest thing to a publication date.
        published_at=_activation_date(raw, detail),
        discovered_at=discovered_at,
        raw_metadata={
            key: raw.get(key)
            for key in ("id", "slug", "status", "remotePercentage", "currency", "offerLanguages", "updatedAt")
        },
    )


def _remote_policy(value: Any) -> RemotePolicy | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
        return None
    if value == 100:
        return RemotePolicy.REMOTE
    return RemotePolicy.ONSITE if value == 0 else RemotePolicy.HYBRID


def _description(detail: Mapping[str, Any] | None) -> str | None:
    if not detail:
        return None
    parts: list[str] = []
    for key, heading in _DESCRIPTION_SECTIONS:
        value = detail.get(key)
        if isinstance(value, list):
            value = "\n".join(f"- {item}" for item in value if isinstance(item, str) and item.strip())
        text = _clean(value) if isinstance(value, str) else ""
        if text:
            parts.append(f"{heading}\n{text}" if heading else text)
    techs = [
        item["name"].strip()
        for item in detail.get("techs") or []
        if isinstance(item, Mapping) and isinstance(item.get("name"), str) and item["name"].strip()
    ]
    if techs:
        parts.append("Tecnologías\n" + ", ".join(dict.fromkeys(techs)))
    return "\n\n".join(parts) or None


def _activation_date(raw: Mapping[str, Any], detail: Mapping[str, Any] | None) -> datetime | None:
    if raw.get("status") != "ACTIVE" or not detail:
        return None
    value = _text(detail.get("lastStatusChange"))
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _clean(value: str) -> str:
    value = re.sub(r"</?u>", "", value)
    value = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", value)  # markdown links keep their label
    return value.replace("**", "").strip()


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _amount(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number > 0 else None
