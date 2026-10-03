"""No-scrape identification of public Greenhouse, Lever, Ashby, Teamtailor, and SmartRecruiters job boards.

Teamtailor is detected only on ``{company}.teamtailor.com``; custom career
domains are not guessed."""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from ai_job_hunter.domain.company_intelligence import (
    ATSDiscoveryConfidence,
    ATSDiscoveryResult,
    ATSProvider,
)

_BOARD_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")


def discover_ats_url(url: str | None) -> ATSDiscoveryResult:
    """Match exact public ATS hosts and extract their first path identifier."""

    if not isinstance(url, str) or not url.strip():
        return _unknown(url if isinstance(url, str) else None, "No career/jobs URL was provided.")
    source_url = url.strip()
    candidate = source_url if "://" in source_url else f"https://{source_url.lstrip('/')}"
    try:
        parsed = urlsplit(candidate)
        host = (parsed.hostname or "").casefold().rstrip(".")
        port = parsed.port
    except ValueError:
        return _unknown(source_url, "The URL is malformed.")
    if parsed.scheme.casefold() not in {"http", "https"} or not host or port not in {None, 80, 443}:
        return _unknown(source_url, "The URL is malformed or uses an unsupported scheme/port.")
    if parsed.username is not None or parsed.password is not None:
        return _unknown(source_url, "URLs containing credentials are not used for ATS discovery.")

    if host == "linkedin.com" or host.endswith(".linkedin.com") or host == "lnkd.in":
        return _unknown(source_url, "LinkedIn jobs URL; no ATS inference is attempted.")

    segments = [unquote(part).strip() for part in parsed.path.split("/") if part.strip()]
    provider: ATSProvider | None = None
    region: str | None = None
    evidence: str | None = None
    identifier: str | None = None
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io", "boards.eu.greenhouse.io"}:
        provider = ATSProvider.GREENHOUSE
        evidence = f"Exact Greenhouse board hostname '{host}' matched; the first path segment is the board token."
    elif host in {"jobs.lever.co", "jobs.eu.lever.co"}:
        provider = ATSProvider.LEVER
        region = "eu" if host == "jobs.eu.lever.co" else "global"
        evidence = f"Exact Lever jobs hostname '{host}' matched; the first path segment is the site slug."
    elif host == "jobs.ashbyhq.com":
        provider = ATSProvider.ASHBY
        evidence = "Exact Ashby jobs hostname matched; the first path segment is the job board name."
    elif host in {"jobs.smartrecruiters.com", "careers.smartrecruiters.com"}:
        provider = ATSProvider.SMARTRECRUITERS
        evidence = f"Exact SmartRecruiters hostname '{host}' matched; the first path segment is the company identifier."
    else:
        label, _, parent = host.partition(".")
        if parent == "teamtailor.com" and label not in {"www", "app", "api"}:
            provider = ATSProvider.TEAMTAILOR
            identifier = label
            evidence = f"Teamtailor career-site subdomain '{host}' matched; the subdomain is the company identifier."

    if provider is None:
        return _unknown(source_url, f"Hostname '{host}' does not match a supported ATS public board pattern.")
    if provider is not ATSProvider.TEAMTAILOR:
        identifier = segments[0] if segments else None
    if identifier is None or not _BOARD_IDENTIFIER.fullmatch(identifier):
        return ATSDiscoveryResult(
            provider=provider,
            identifier=None,
            region=region,
            confidence=ATSDiscoveryConfidence.UNKNOWN,
            evidence=f"{evidence} No valid board identifier appears in the path.",
            source_url=source_url,
        )
    return ATSDiscoveryResult(
        provider=provider,
        identifier=identifier,
        region=region,
        confidence=ATSDiscoveryConfidence.DIRECT_URL_PATTERN,
        evidence=evidence,
        source_url=source_url,
    )


def _unknown(source_url: str | None, evidence: str) -> ATSDiscoveryResult:
    return ATSDiscoveryResult(
        provider=ATSProvider.UNKNOWN,
        confidence=ATSDiscoveryConfidence.UNKNOWN,
        evidence=evidence,
        source_url=source_url,
    )
