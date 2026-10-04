"""Validated imports and conservative careers-page resolution for company leads."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from collections.abc import Callable, Iterable, Sequence
from typing import TYPE_CHECKING
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_job_hunter.ats_discovery import discover_ats_url
from ai_job_hunter.deduplication.normalization import (
    extract_company_domain,
    normalize_company_name,
)
from ai_job_hunter.domain.company_intelligence import (
    ATSDiscoveryResult,
    ATSProvider,
    CompanyEvidenceRecord,
    CompanyEvidenceType,
)
from ai_job_hunter.models import Company, CompanyEvidence, CompanyLead, CompanyLeadStatus
from ai_job_hunter.services.company_intelligence import upsert_company_evidence_record

if TYPE_CHECKING:
    from ai_job_hunter.company_sources import CompanySourceBatch

COMPANY_LEAD_USER_AGENT = "AI-Job-Hunter/0.1 (public company careers discovery)"
CAREER_LINK_PATTERN = re.compile(
    r"\b(?:career|careers|job|jobs|work\s+with\s+us|join(?:\s+our)?\s+team|open\s+positions?)\b",
    re.IGNORECASE,
)
# Modern public career sites include large but still manageable HTML bundles.
MAX_HTML_BYTES = 5_000_000
MAX_REDIRECTS = 4


class CompanyLeadInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    company_name: str = Field(min_length=1, max_length=255)
    website_url: str | None = Field(default=None, max_length=2048)
    careers_url: str | None = Field(default=None, max_length=2048)
    source_type: str = Field(min_length=1, max_length=100)
    source_label: str = Field(min_length=1, max_length=255)
    source_url: str | None = Field(default=None, max_length=2048)
    location_hint: str | None = Field(default=None, max_length=255)
    hiring_hint: str | None = Field(default=None, max_length=512)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("company_name")
    @classmethod
    def company_name_is_normalizable(cls, value: str) -> str:
        if normalize_company_name(value) is None:
            raise ValueError("company_name must contain letters or numbers")
        return value

    @field_validator("website_url", "careers_url", "source_url")
    @classmethod
    def urls_are_http_urls(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = urlsplit(value)
            _ = parsed.port
        except ValueError as error:
            raise ValueError("URL is malformed") from error
        if (
            parsed.scheme.casefold() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("URL must be an http(s) URL without credentials")
        return value


class CompanyLeadsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    leads: list[CompanyLeadInput] = Field(min_length=1)


class CompanyLeadsConfigError(ValueError):
    """Missing, malformed, or invalid local company-leads JSON."""


def load_company_leads(path: str | Path) -> CompanyLeadsConfig:
    config_path = Path(path)
    try:
        contents = config_path.read_text(encoding="utf-8")
    except OSError as error:
        raise CompanyLeadsConfigError(f"Cannot read company leads config '{config_path}'.") from error
    try:
        payload = json.loads(contents)
    except json.JSONDecodeError as error:
        raise CompanyLeadsConfigError(
            f"Company leads config is not valid JSON at line {error.lineno}, column {error.colno}."
        ) from error
    try:
        return CompanyLeadsConfig.model_validate(payload)
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc']) or '<root>'}: {item['msg']}"
            for item in error.errors()
        )
        raise CompanyLeadsConfigError(f"Invalid company leads config: {details}") from error


@dataclass(frozen=True, slots=True)
class CompanyLeadImportSummary:
    created: int
    duplicates: int
    updated: int
    unchanged: int


@dataclass(frozen=True, slots=True)
class CompanyLeadResolution:
    lead_id: UUID
    company_name: str
    status: CompanyLeadStatus
    careers_url: str | None
    ats_provider: ATSProvider | None
    ats_identifier: str | None
    note: str


@dataclass(frozen=True, slots=True)
class CompanyLeadResolveSummary:
    selected: int
    results: tuple[CompanyLeadResolution, ...]

    def count(self, status: CompanyLeadStatus) -> int:
        return sum(item.status is status for item in self.results)


@dataclass(frozen=True, slots=True)
class _PageOutcome:
    status: CompanyLeadStatus
    careers_url: str | None
    landing_url: str | None
    discovery: ATSDiscoveryResult | None
    note: str


class CareerPageDiscoveryError(ValueError):
    """A bounded public-page request or careers link could not be inspected."""


def import_company_leads(
    session: Session, config: CompanyLeadsConfig
) -> CompanyLeadImportSummary:
    """Idempotently merge rows by normalized name and exact website domain."""

    rows = session.scalars(select(CompanyLead).order_by(CompanyLead.id)).all()
    by_identity = {(row.normalized_name, row.domain_key): row for row in rows}
    created = duplicates = updated = unchanged = 0
    transaction = session.begin_nested() if session.in_transaction() else session.begin()
    with transaction:
        for item in config.leads:
            name = normalize_company_name(item.company_name)
            assert name is not None
            domain = extract_company_domain(item.website_url) or ""
            key = (name, domain)
            provenance = _provenance_entry(item)
            lead = by_identity.get(key)
            if lead is None:
                lead = CompanyLead(
                    company_name=item.company_name,
                    normalized_name=name,
                    domain_key=domain,
                    website_url=item.website_url,
                    careers_url=item.careers_url,
                    source_type=item.source_type,
                    source_label=item.source_label,
                    source_url=item.source_url,
                    location_hint=item.location_hint,
                    hiring_hint=item.hiring_hint,
                    notes=item.notes,
                    source_provenance=[provenance],
                    status=CompanyLeadStatus.NEW.value,
                )
                session.add(lead)
                by_identity[key] = lead
                created += 1
                continue

            duplicates += 1
            changed = False
            provenance_rows = list(lead.source_provenance or [])
            if provenance not in provenance_rows:
                provenance_rows.append(provenance)
                lead.source_provenance = provenance_rows
                changed = True
            for field_name in ("website_url", "careers_url", "source_url", "location_hint", "hiring_hint", "notes"):
                current = getattr(lead, field_name)
                incoming = getattr(item, field_name)
                if current is None and incoming is not None:
                    setattr(lead, field_name, incoming)
                    changed = True
            if changed:
                updated += 1
            else:
                unchanged += 1
        session.flush()
    return CompanyLeadImportSummary(created, duplicates, updated, unchanged)


def list_company_leads(
    session: Session,
    *,
    status: CompanyLeadStatus | None = None,
    limit: int = 20,
) -> list[CompanyLead]:
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be from 1 to 1000")
    statement = select(CompanyLead).order_by(CompanyLead.company_name, CompanyLead.created_at)
    if status is not None:
        statement = statement.where(CompanyLead.status == status.value)
    return list(session.scalars(statement.limit(limit)).all())


def get_company_lead(session: Session, lead_id: UUID) -> CompanyLead | None:
    return session.get(CompanyLead, lead_id)


def resolve_company_leads(
    session: Session,
    *,
    limit: int = 20,
    retry_failed: bool = False,
    recheck_unsupported: bool = False,
    client: httpx.Client | None = None,
    host_resolver: Callable[[str, int], Iterable[str]] | None = None,
) -> CompanyLeadResolveSummary:
    """Resolve NEW leads through bounded public HTML inspection and exact ATS matching."""

    if not 1 <= limit <= 100:
        raise ValueError("limit must be from 1 to 100")
    resolver = host_resolver or _resolve_host
    statuses = [CompanyLeadStatus.NEW.value]
    if retry_failed:
        statuses.append(CompanyLeadStatus.FAILED.value)
    if recheck_unsupported:
        # After a new ATS connector is added, careers pages that pointed at an
        # unknown board may now resolve to a supported one.
        statuses.extend((CompanyLeadStatus.RESOLVED.value, CompanyLeadStatus.UNSUPPORTED_ATS.value))
    leads = list(
        session.scalars(
            select(CompanyLead)
            .where(CompanyLead.status.in_(statuses))
            # Least recently checked first, so repeated rechecks walk every lead.
            .order_by(CompanyLead.updated_at, CompanyLead.created_at, CompanyLead.company_name)
            .limit(limit)
        ).all()
    )
    own_client = client is None
    http_client = client or httpx.Client(
        timeout=httpx.Timeout(12.0),
        headers={"Accept": "text/html,application/xhtml+xml;q=0.9", "User-Agent": COMPANY_LEAD_USER_AGENT},
        follow_redirects=False,
    )
    results: list[CompanyLeadResolution] = []
    try:
        for lead in leads:
            try:
                outcome = _resolve_one(lead, http_client, resolver)
                with session.begin_nested():
                    # Mark it checked even when nothing changed (recheck order).
                    lead.updated_at = datetime.now(UTC)
                    lead.status = outcome.status.value
                    lead.careers_url = outcome.careers_url or lead.careers_url
                    lead.resolution_note = outcome.note
                    lead.ats_provider = (
                        outcome.discovery.provider.value if outcome.discovery and outcome.discovery.is_supported else None
                    )
                    lead.ats_identifier = outcome.discovery.identifier if outcome.discovery and outcome.discovery.is_supported else None
                    lead.ats_region = outcome.discovery.region if outcome.discovery and outcome.discovery.is_supported else None
                    if outcome.status is CompanyLeadStatus.SUPPORTED_ATS and outcome.discovery is not None:
                        ambiguity = _existing_company_conflict(session, lead)
                        if ambiguity:
                            lead.status = CompanyLeadStatus.AMBIGUOUS.value
                            lead.ats_provider = None
                            lead.ats_identifier = None
                            lead.ats_region = None
                            lead.resolution_note = ambiguity
                        else:
                            persisted = _persist_supported_lead(session, lead, outcome)
                            lead.company_id = persisted
                    session.flush()
                status = CompanyLeadStatus(lead.status)
                results.append(
                    CompanyLeadResolution(
                        lead_id=lead.id,
                        company_name=lead.company_name,
                        status=status,
                        careers_url=lead.careers_url,
                        ats_provider=(
                            ATSProvider(lead.ats_provider) if lead.ats_provider is not None else None
                        ),
                        ats_identifier=lead.ats_identifier,
                        note=lead.resolution_note or outcome.note,
                    )
                )
            except (CareerPageDiscoveryError, httpx.RequestError) as error:
                with session.begin_nested():
                    lead.updated_at = datetime.now(UTC)
                    lead.status = CompanyLeadStatus.FAILED.value
                    lead.resolution_note = str(error)[:1000]
                    lead.ats_provider = None
                    lead.ats_identifier = None
                    lead.ats_region = None
                    session.flush()
                results.append(
                    CompanyLeadResolution(
                        lead_id=lead.id,
                        company_name=lead.company_name,
                        status=CompanyLeadStatus.FAILED,
                        careers_url=lead.careers_url,
                        ats_provider=None,
                        ats_identifier=None,
                        note=lead.resolution_note or "Public careers page inspection failed.",
                    )
                )
    finally:
        if own_client:
            http_client.close()
    return CompanyLeadResolveSummary(selected=len(leads), results=tuple(results))


def _resolve_one(
    lead: CompanyLead,
    client: httpx.Client,
    host_resolver: Callable[[str, int], Iterable[str]],
) -> _PageOutcome:
    if lead.careers_url:
        return _inspect_careers_url(
            lead.careers_url,
            website_url=lead.website_url,
            explicit=True,
            client=client,
            host_resolver=host_resolver,
        )
    if not lead.website_url:
        return _PageOutcome(
            CompanyLeadStatus.AMBIGUOUS,
            None,
            None,
            None,
            "No website_url or careers_url was supplied; domain lookup is intentionally not guessed.",
        )

    final_url, html = _fetch_html(lead.website_url, client, host_resolver)
    final_discovery = discover_ats_url(final_url)
    if final_discovery.is_supported:
        return _supported_outcome(final_url, final_url, final_discovery)
    if final_discovery.provider is not ATSProvider.UNKNOWN:
        return _PageOutcome(
            CompanyLeadStatus.AMBIGUOUS,
            final_url,
            final_url,
            final_discovery,
            "The redirected supported ATS URL has no valid board identifier.",
        )

    page_links = _parse_links(final_url, html)
    direct_ats = _direct_ats_links(page_links)
    if direct_ats:
        return _outcome_from_ats_links(direct_ats, final_url)

    careers = [url for url, label in page_links if _is_career_link(url, label)]
    careers = list(dict.fromkeys(careers))
    if not careers and _is_career_link(final_url, ""):
        careers = [final_url]
    if not careers:
        return _PageOutcome(
            CompanyLeadStatus.NO_CAREERS_PAGE,
            None,
            None,
            None,
            "No careers/jobs link was found on the supplied website page.",
        )
    if len(careers) > 1:
        return _PageOutcome(
            CompanyLeadStatus.AMBIGUOUS,
            None,
            None,
            None,
            f"Found {len(careers)} distinct careers/jobs links; none was selected automatically.",
        )
    return _inspect_careers_url(
        careers[0],
        website_url=lead.website_url,
        explicit=False,
        client=client,
        host_resolver=host_resolver,
    )


def _inspect_careers_url(
    url: str,
    *,
    website_url: str | None,
    explicit: bool,
    client: httpx.Client,
    host_resolver: Callable[[str, int], Iterable[str]],
) -> _PageOutcome:
    direct = discover_ats_url(url)
    if direct.is_supported:
        return _supported_outcome(url, url, direct)
    if direct.provider is not ATSProvider.UNKNOWN:
        return _PageOutcome(
            CompanyLeadStatus.AMBIGUOUS,
            url,
            url,
            direct,
            "The URL belongs to a supported ATS host but has no valid board identifier.",
        )
    if _is_external_url(url, website_url):
        return _PageOutcome(
            CompanyLeadStatus.UNSUPPORTED_ATS,
            url,
            url,
            None,
            "A careers page was found on an unrecognized external host; no supported ATS URL pattern matched.",
        )

    final_url, html = _fetch_html(url, client, host_resolver)
    final_discovery = discover_ats_url(final_url)
    if final_discovery.is_supported:
        return _supported_outcome(final_url, final_url, final_discovery)
    if final_discovery.provider is not ATSProvider.UNKNOWN:
        return _PageOutcome(
            CompanyLeadStatus.AMBIGUOUS,
            final_url,
            final_url,
            final_discovery,
            "The redirected supported ATS URL has no valid board identifier.",
        )

    links = _parse_links(final_url, html)
    direct_ats = _direct_ats_links(links)
    if direct_ats:
        return _outcome_from_ats_links(direct_ats, final_url)
    external = _is_external_url(final_url, website_url)
    if external:
        return _PageOutcome(
            CompanyLeadStatus.UNSUPPORTED_ATS,
            final_url,
            final_url,
            None,
            "A careers page was found on an unrecognized external host; no supported ATS was identified.",
        )
    return _PageOutcome(
        CompanyLeadStatus.RESOLVED,
        final_url,
        final_url,
        None,
        "A careers page was found, but it does not identify a supported ATS board.",
    )


def _supported_outcome(
    careers_url: str, landing_url: str, discovery: ATSDiscoveryResult
) -> _PageOutcome:
    return _PageOutcome(
        CompanyLeadStatus.SUPPORTED_ATS,
        careers_url,
        landing_url,
        discovery,
        f"Supported {discovery.provider.value} board identified from an exact public URL pattern.",
    )


def _outcome_from_ats_links(links: Sequence[str], landing_url: str) -> _PageOutcome:
    discoveries = [discover_ats_url(url) for url in links]
    if any(item.provider is not ATSProvider.UNKNOWN and not item.is_supported for item in discoveries):
        return _PageOutcome(
            CompanyLeadStatus.AMBIGUOUS,
            landing_url,
            landing_url,
            next(item for item in discoveries if item.provider is not ATSProvider.UNKNOWN),
            "A supported ATS host was linked without an identifiable board slug.",
        )
    supported = [item for item in discoveries if item.is_supported]
    unique = {(item.provider, item.identifier, item.region): item for item in supported}
    if len(unique) > 1:
        return _PageOutcome(
            CompanyLeadStatus.AMBIGUOUS,
            landing_url,
            landing_url,
            None,
            f"Found {len(unique)} distinct supported ATS boards; none was selected automatically.",
        )
    discovery = next(iter(unique.values()), None)
    if discovery is None:
        return _PageOutcome(
            CompanyLeadStatus.UNSUPPORTED_ATS,
            landing_url,
            landing_url,
            None,
            "The careers page links to an unrecognized external jobs host.",
        )
    return _supported_outcome(discovery.source_url or landing_url, landing_url, discovery)


def _fetch_html(
    url: str,
    client: httpx.Client,
    host_resolver: Callable[[str, int], Iterable[str]],
) -> tuple[str, str]:
    current = url
    prior_scheme: str | None = None
    for redirect_count in range(MAX_REDIRECTS + 1):
        _validate_public_url(current, host_resolver)
        parsed = urlsplit(current)
        if prior_scheme == "https" and parsed.scheme.casefold() != "https":
            raise CareerPageDiscoveryError("HTTPS redirect downgrade was blocked.")
        try:
            with client.stream(
                "GET",
                current,
                follow_redirects=False,
                headers={"Accept": "text/html,application/xhtml+xml;q=0.9", "User-Agent": COMPANY_LEAD_USER_AGENT},
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise CareerPageDiscoveryError("Careers page redirect did not include a target URL.")
                    if redirect_count >= MAX_REDIRECTS:
                        raise CareerPageDiscoveryError("Careers page exceeded the redirect limit.")
                    prior_scheme = parsed.scheme.casefold()
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").casefold()
                if content_type and "html" not in content_type:
                    raise CareerPageDiscoveryError("Careers page response was not HTML.")
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_HTML_BYTES:
                        raise CareerPageDiscoveryError("Careers page exceeded the HTML size limit.")
                    chunks.append(chunk)
                encoding = response.encoding or "utf-8"
                return str(response.url), b"".join(chunks).decode(encoding, errors="replace")
        except httpx.HTTPStatusError as error:
            raise CareerPageDiscoveryError(
                f"Careers page returned HTTP {error.response.status_code}."
            ) from error
        except httpx.RequestError as error:
            raise CareerPageDiscoveryError(
                f"Careers page request failed ({type(error).__name__})."
            ) from error
    raise CareerPageDiscoveryError("Careers page could not be resolved within the redirect limit.")


def _validate_public_url(
    url: str, host_resolver: Callable[[str, int], Iterable[str]]
) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port or (443 if parsed.scheme.casefold() == "https" else 80)
    except ValueError as error:
        raise CareerPageDiscoveryError("Careers page URL is malformed.") from error
    host = parsed.hostname
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise CareerPageDiscoveryError("Only credential-free public http(s) career pages are fetched.")
    if port not in {80, 443}:
        raise CareerPageDiscoveryError("Career-page requests are limited to standard HTTP and HTTPS ports.")
    if host.casefold() == "localhost" or host.casefold().endswith((".localhost", ".local", ".internal")):
        raise CareerPageDiscoveryError("Local or internal career-page hosts are blocked.")
    try:
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            addresses = [ipaddress.ip_address(value) for value in host_resolver(host, port)]
    except (OSError, ValueError, socket.gaierror) as error:
        raise CareerPageDiscoveryError("Career-page hostname did not resolve to a public address.") from error
    if not addresses or any(not address.is_global for address in addresses):
        raise CareerPageDiscoveryError("Private, loopback, or non-public career-page addresses are blocked.")


def _resolve_host(host: str, port: int) -> Iterable[str]:
    return tuple(
        dict.fromkeys(
            item[4][0]
            for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        )
    )


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._text)))
            self._href = None
            self._text = []


def _parse_links(base_url: str, html: str) -> list[tuple[str, str]]:
    parser = _AnchorParser()
    parser.feed(html)
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for href, label in parser.links:
        absolute = urljoin(base_url, href.strip()) if href.strip() else ""
        try:
            parsed = urlsplit(absolute)
        except ValueError:
            continue
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
            continue
        normalized = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
        if normalized not in seen:
            links.append((normalized, label.strip()))
            seen.add(normalized)
    return links


def _is_career_link(url: str, label: str) -> bool:
    path = urlsplit(url).path.replace("_", " ").replace("-", " ")
    return bool(CAREER_LINK_PATTERN.search(f"{label} {path}"))


def _direct_ats_links(links: Sequence[tuple[str, str]]) -> list[str]:
    return list(
        dict.fromkeys(
            url for url, _label in links if discover_ats_url(url).provider is not ATSProvider.UNKNOWN
        )
    )


def _is_external_url(url: str, website_url: str | None) -> bool:
    if not website_url:
        return False
    page_domain = extract_company_domain(url)
    website_domain = extract_company_domain(website_url)
    if page_domain is None or website_domain is None:
        return False
    return not (
        page_domain == website_domain
        or page_domain.endswith(f".{website_domain}")
        or website_domain.endswith(f".{page_domain}")
    )


def _existing_company_conflict(session: Session, lead: CompanyLead) -> str | None:
    same_name = [
        company
        for company in session.scalars(select(Company).order_by(Company.id)).all()
        if normalize_company_name(company.name) == lead.normalized_name
    ]
    domain = extract_company_domain(lead.website_url)
    if domain is None:
        if len(same_name) > 1 or (same_name and extract_company_domain(same_name[0].website_url)):
            return "Existing Company Intelligence records conflict with this lead's missing website domain."
        return None
    exact_domain = [item for item in same_name if extract_company_domain(item.website_url) == domain]
    if len(exact_domain) > 1:
        return "Multiple existing Company records share this normalized name and domain."
    conflicting = [
        item
        for item in same_name
        if extract_company_domain(item.website_url) not in {None, domain}
    ]
    if not exact_domain and conflicting:
        return "An existing Company has the same normalized name but a different website domain."
    return None


def _persist_supported_lead(
    session: Session, lead: CompanyLead, outcome: _PageOutcome
) -> UUID:
    discovery = outcome.discovery
    assert discovery is not None and discovery.is_supported
    careers_url = outcome.careers_url or discovery.source_url
    assert careers_url is not None
    source_key = f"{lead.id}:career-page"
    provenance = {
        "lead_id": str(lead.id),
        "source_type": lead.source_type,
        "source_label": lead.source_label,
        "source_url": lead.source_url,
        "resolution_basis": "website_careers_link_to_supported_ats",
        "landing_url": outcome.landing_url,
        "discovery_evidence": discovery.evidence,
        "location_hint": lead.location_hint,
        "hiring_hint": lead.hiring_hint,
        "hints_are_not_verified_company_facts": True,
    }
    record = CompanyEvidenceRecord(
        provider="company_lead",
        evidence_type=CompanyEvidenceType.CAREER_PAGE,
        source_key=source_key,
        company_name=lead.company_name,
        source_url=careers_url,
        external_identifier=f"{discovery.provider.value}:{discovery.identifier}",
        website_url=lead.website_url,
        structured_data={
            "career_page_url": careers_url,
            "career_page_landing_url": outcome.landing_url,
            "discovery_chain": provenance,
        },
        raw_metadata=provenance,
    )
    result = upsert_company_evidence_record(session, record, raw_metadata=provenance)
    return result.company.id


def _provenance_entry(item: CompanyLeadInput) -> dict[str, str | None]:
    return {
        "source_type": item.source_type,
        "source_label": item.source_label,
        "source_url": item.source_url,
        "website_url": item.website_url,
        "careers_url": item.careers_url,
        "location_hint": item.location_hint,
        "hiring_hint": item.hiring_hint,
        "notes": item.notes,
    }


def leads_from_company_directories(batches: Iterable["CompanySourceBatch"]) -> CompanyLeadsConfig:
    """Turn curated company directories (Spanish Top Tech, Manfred) into leads.

    A directory only proves the company exists and is worth checking; jobs are
    still verified on the official careers page/ATS. LinkedIn job searches are
    never used as careers pages (no LinkedIn scraping); they are kept as notes.
    """

    leads: list[CompanyLeadInput] = []
    for batch in batches:
        for record in batch.records:
            data = record.structured_data or {}
            urls = data.get("career_page_urls") or [data.get("career_page_url")]
            usable = [url for url in urls if isinstance(url, str) and url and "linkedin.com" not in url.casefold()]
            linkedin = [url for url in urls if isinstance(url, str) and "linkedin.com" in url.casefold()]
            compensation = data.get("compensation") if isinstance(data.get("compensation"), dict) else {}
            if compensation.get("base_annual_eur"):
                hint = (
                    f"Spanish Top Tech: median base {compensation['base_annual_eur']} EUR/year "
                    "for Spain-based software engineers with 5+ years"
                )
            elif data.get("public_salary"):
                hint = "Manfred directory: publishes salary ranges in job offers"
            else:
                hint = None
            leads.append(
                CompanyLeadInput(
                    company_name=record.company_name,
                    careers_url=usable[0] if usable else None,
                    source_type="curated_directory",
                    source_label=batch.provider,
                    source_url=record.source_url or batch.readme_url,
                    hiring_hint=hint[:512] if hint else None,
                    notes=("LinkedIn jobs page (not used): " + linkedin[0])[:4000] if linkedin else None,
                )
            )
    if not leads:
        raise CompanyLeadsConfigError("The company directories contained no companies.")
    return CompanyLeadsConfig(leads=leads)
