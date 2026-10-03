"""Small, explainable normalizers used only to compare job identity."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import SplitResult, parse_qsl, unquote, urlencode, urlsplit, urlunsplit


_LEGAL_SUFFIXES = (
    ("incorporated",),
    ("corporation",),
    ("limited",),
    ("gmbh",),
    ("ltd",),
    ("inc",),
    ("llc",),
    ("plc",),
    ("corp",),
    ("s", "l"),
    ("s", "a"),
    ("sa",),
)
_CONTEXT_TOKENS = {
    "remote",
    "hybrid",
    "onsite",
    "spain",
    "espana",
    "eu",
    "europe",
    "emea",
    "worldwide",
}
_TITLE_SENIORITY = {
    "intern", "graduate", "junior", "mid", "senior", "staff", "principal",
    "lead", "manager", "director", "head",
}
_TITLE_ALIASES = {
    "jr": "junior",
    "sr": "senior",
    "middle": "mid",
    "developer": "engineer",
    # Internship words in German/Spanish titles map to the intern seniority.
    "praktikum": "intern",
    "praktikant": "intern",
    "werkstudent": "intern",
    # Executive titles sit at the top of the seniority scale.
    "chief": "head",
    "vp": "head",
    "becario": "intern",
    "becaria": "intern",
}
_GENERIC_PATH_SEGMENTS = {"", "job", "jobs", "career", "careers", "apply", "application", "applications"}
_JOB_PATH_MARKERS = {"job", "jobs", "role", "roles", "position", "positions", "opening", "openings"}
_STABLE_QUERY_KEYS = {
    "ashby_jid",
    "gh_jid",
    "job_id",
    "jobid",
    "jid",
    "lever_id",
    "lever-job-id",
    "posting_id",
    "requisition_id",
    "req_id",
}
_TRACKING_QUERY_KEYS = {"campaign", "gh_src", "li_fat_id", "ref", "referrer", "source", "tracking", "trk", "via"}
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class NormalizedTitle:
    """Role tokens and seniority kept separate for safe comparisons."""

    tokens: frozenset[str]
    seniority: frozenset[str]


def normalize_company_name(name: str | None) -> str | None:
    """Casefold a name and remove only a recognized trailing legal suffix."""

    tokens = _words(name or "")
    changed = True
    while changed and tokens:
        changed = False
        for suffix in _LEGAL_SUFFIXES:
            if len(tokens) >= len(suffix) and tuple(tokens[-len(suffix) :]) == suffix:
                del tokens[-len(suffix) :]
                changed = True
                break
    normalized = " ".join(tokens)
    return normalized or None


def extract_company_domain(website: str | None) -> str | None:
    """Return the exact hostname, ignoring scheme, port, and a leading www."""

    if not website or not website.strip():
        return None
    parsed = _parse_url(website)
    if parsed is None or parsed.hostname is None:
        return None
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname or None


def normalize_job_title(title: str) -> NormalizedTitle:
    """Remove small location/work-mode suffixes and capture seniority tokens."""

    value = unicodedata.normalize("NFKC", title).casefold().strip()

    def remove_context_parenthetical(match: re.Match[str]) -> str:
        raw_content = match.group(1) if match.group(1) is not None else match.group(2)
        content = _words(raw_content or "")
        if content and all(token in _CONTEXT_TOKENS | {"on", "site", "from"} for token in content):
            return " "
        return match.group(0)

    value = re.sub(r"\(([^()]*)\)|\[([^\[\]]*)\]", remove_context_parenthetical, value)
    parts = re.split(r"\s+[-–—|]\s+", value)
    while len(parts) > 1:
        trailing = _words(parts[-1])
        if trailing and all(token in _CONTEXT_TOKENS | {"on", "site", "from"} for token in trailing):
            parts.pop()
        else:
            break

    tokens = _words(" ".join(parts))
    role_tokens: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "on" and index + 1 < len(tokens) and tokens[index + 1] == "site":
            index += 2
            continue
        if token in {"remote", "hybrid", "onsite"}:
            index += 1
            continue
        role_tokens.append(_TITLE_ALIASES.get(token, token))
        index += 1

    seniority = frozenset(token for token in role_tokens if token in _TITLE_SENIORITY)
    base_tokens = frozenset(token for token in role_tokens if token not in _TITLE_SENIORITY)
    return NormalizedTitle(tokens=base_tokens, seniority=seniority)


def normalize_location(location: str | None) -> str | None:
    """Normalize punctuation and remove common remote/geographic qualifiers."""

    tokens = [token for token in _words(location or "") if token not in _CONTEXT_TOKENS | {"from"}]
    normalized = " ".join(tokens)
    return normalized or None


def normalize_job_url(url: str | None) -> str | None:
    """Canonicalize URL casing and tracking parameters without a network lookup."""

    if not url or not url.strip():
        return None
    parsed = _parse_url(url)
    if parsed is None or parsed.hostname is None:
        return None

    hostname = parsed.hostname.lower().rstrip(".")
    if hostname.startswith("www."):
        hostname = hostname[4:]
    port = parsed.port
    netloc = hostname if port is None or port in {80, 443} else f"{hostname}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path).rstrip("/") or "/"
    query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered_key = key.casefold()
        if lowered_key.startswith("utm_") or lowered_key in _TRACKING_QUERY_KEYS:
            continue
        query.append((key, value))
    query.sort()
    return urlunsplit(("https", netloc, path, urlencode(query, doseq=True), ""))


def is_job_specific_url(url: str | None) -> bool:
    """Reject home/careers pages; accept a job route or a stable job ID query."""

    normalized = normalize_job_url(url)
    if normalized is None:
        return False
    parsed = urlsplit(normalized)
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.casefold() in _STABLE_QUERY_KEYS and value.strip():
            return True

    segments = [unquote(segment).casefold() for segment in parsed.path.split("/") if segment]
    if any(_UUID_PATTERN.fullmatch(segment) or re.fullmatch(r"\d{4,}", segment) for segment in segments):
        return True
    return any(
        segment in _JOB_PATH_MARKERS and index + 1 < len(segments)
        and segments[index + 1] not in _GENERIC_PATH_SEGMENTS
        for index, segment in enumerate(segments)
    )


def _words(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    unaccented = "".join(character for character in normalized if not unicodedata.combining(character))
    return re.findall(r"[^\W_]+", unaccented, flags=re.UNICODE)


def _parse_url(value: str) -> SplitResult | None:
    candidate = value.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate.lstrip('/')}"
    try:
        parsed = urlsplit(candidate)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        _ = parsed.port  # Force malformed ports to fail here rather than later.
        return parsed
    except ValueError:
        return None
