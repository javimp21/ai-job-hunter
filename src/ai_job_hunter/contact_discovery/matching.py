"""Conservative contact identity matching without fuzzy auto-merges."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from ai_job_hunter.contact_discovery.domain import (
    ContactCandidate,
    ContactMatch,
    ContactMatchDecision,
    ContactMatchSignals,
)
from ai_job_hunter.deduplication.normalization import normalize_company_name


def normalize_contact_email(email: str | None) -> str | None:
    """Normalize an email for exact identity comparison, never infer one."""

    if not email or not email.strip() or "@" not in email:
        return None
    local, domain = email.strip().rsplit("@", 1)
    if not local.strip() or not domain.strip():
        return None
    return f"{local.strip()}@{domain.strip()}".casefold()


def canonical_linkedin_profile_url(url: str | None) -> str | None:
    """Canonicalize an explicitly supplied LinkedIn member profile URL.

    Tracking query strings, fragments, locale hosts and a leading ``www`` are
    discarded. Company pages and unrelated URLs are not person identifiers.
    No page is fetched or scraped.
    """

    if not url or not url.strip():
        return None
    value = url.strip()
    if "://" not in value:
        value = f"https://{value.lstrip('/')}"
    try:
        parsed = urlsplit(value)
        hostname = (parsed.hostname or "").casefold().rstrip(".")
        _ = parsed.port
    except ValueError:
        return None
    if parsed.scheme.casefold() not in {"http", "https"}:
        return None
    if hostname == "www.linkedin.com":
        hostname = "linkedin.com"
    elif hostname.endswith(".linkedin.com"):
        # LinkedIn uses localized subdomains such as es.linkedin.com.
        hostname = "linkedin.com"
    if hostname != "linkedin.com":
        return None

    segments = [part.casefold() for part in parsed.path.split("/") if part]
    if len(segments) < 2 or segments[0] not in {"in", "pub"}:
        return None
    path = "/" + "/".join(segments)
    return urlunsplit(("https", "linkedin.com", path, "", ""))


def match_contacts(left: ContactCandidate, right: ContactCandidate) -> ContactMatch:
    """Compare two records using exact strong signals and a weak name/company key.

    A disagreement between populated strong identifiers prevents automatic
    deduplication even when another strong identifier agrees. Name plus
    company can only produce ``POSSIBLE_MATCH``.
    """

    left_provider_id = _provider_id(left)
    right_provider_id = _provider_id(right)
    left_email = normalize_contact_email(left.email)
    right_email = normalize_contact_email(right.email)
    left_linkedin = canonical_linkedin_profile_url(left.linkedin_url)
    right_linkedin = canonical_linkedin_profile_url(right.linkedin_url)

    strong_matches: list[str] = []
    strong_conflicts: list[str] = []
    if left_provider_id is not None and right_provider_id is not None:
        if left_provider_id == right_provider_id:
            strong_matches.append("provider_external_id")
        elif left_provider_id[0] == right_provider_id[0]:
            strong_conflicts.append("provider_external_id")
    if left_email is not None and right_email is not None:
        (strong_matches if left_email == right_email else strong_conflicts).append("email")
    if left_linkedin is not None and right_linkedin is not None:
        (strong_matches if left_linkedin == right_linkedin else strong_conflicts).append("linkedin_url")

    left_name = _normalize_person_name(left.full_name)
    right_name = _normalize_person_name(right.full_name)
    left_company = normalize_company_name(left.company)
    right_company = normalize_company_name(right.company)
    name_company_match = bool(
        left_name
        and right_name
        and left_company
        and right_company
        and left_name == right_name
        and left_company == right_company
    )

    if strong_matches and not strong_conflicts:
        decision = ContactMatchDecision.MATCH
        reasons = ("At least one strong identity signal agrees, with no populated strong-identifier conflict.",)
    elif strong_matches:
        decision = ContactMatchDecision.POSSIBLE_MATCH
        reasons = ("Strong signals conflict; keep the records separate for review.",)
    elif name_company_match:
        decision = ContactMatchDecision.POSSIBLE_MATCH
        reasons = ("Name and company agree, but weak signals never authorize an automatic merge.",)
    else:
        decision = ContactMatchDecision.NO_MATCH
        reasons = ("No exact strong identity match or exact name-and-company match was found.",)

    return ContactMatch(
        decision=decision,
        signals=ContactMatchSignals(
            strong_matches=tuple(strong_matches),
            strong_conflicts=tuple(strong_conflicts),
            name_company_match=name_company_match,
        ),
        reasons=reasons,
    )


def _provider_id(candidate: ContactCandidate) -> tuple[str, str] | None:
    provider = candidate.provider.strip().casefold()
    external_id = candidate.external_id.strip() if candidate.external_id else ""
    if not provider or not external_id:
        return None
    # External IDs are kept case-sensitive because providers may issue IDs
    # whose case is significant.
    return provider, external_id


def _normalize_person_name(name: str | None) -> str | None:
    if not name or not name.strip():
        return None
    normalized = unicodedata.normalize("NFKD", name).casefold()
    plain = "".join(char for char in normalized if not unicodedata.combining(char))
    value = " ".join(re.findall(r"[^\W_]+", plain, flags=re.UNICODE))
    return value or None
