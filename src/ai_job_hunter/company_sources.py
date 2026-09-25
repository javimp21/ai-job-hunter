"""Offline parsers and explicit, low-volume refreshes for company sources."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from ai_job_hunter.deduplication.normalization import normalize_company_name
from ai_job_hunter.domain.company_intelligence import CompanyEvidenceRecord, CompanyEvidenceType

SPANISH_TOP_TECH = "spanish_top_tech_companies"
MANFRED_PUBLIC_SALARY = "manfred_public_salary_companies"
REMOTE_ES = "remote_es"

SPANISH_TOP_TECH_README = "https://raw.githubusercontent.com/pugarte7/spanish-top-tech-companies/main/README.md"
SPANISH_TOP_TECH_REPOSITORY = "https://github.com/pugarte7/spanish-top-tech-companies"
SPANISH_TOP_TECH_LICENSE = "CC BY-SA 4.0"
SPANISH_TOP_TECH_LICENSE_URL = "https://github.com/pugarte7/spanish-top-tech-companies/blob/main/LICENSE-DATA"
MANFRED_README = "https://raw.githubusercontent.com/getmanfred/companies-with-public-salary/main/README.md"
MANFRED_REPOSITORY = "https://github.com/getmanfred/companies-with-public-salary"
MANFRED_LICENSE = "Apache-2.0"
MANFRED_LICENSE_URL = "https://github.com/getmanfred/companies-with-public-salary/blob/main/LICENSE"
REMOTE_ES_REPOSITORY = "https://github.com/remote-es/remotes"
REMOTE_ES_SKIP_REASON = (
    "No explicit data license was present in the public repository metadata or root files; "
    "the company list is therefore not copied or automatically ingested."
)
DEFAULT_SNAPSHOT_DIR = Path("data/local/company-intelligence/source-snapshots")
MAX_README_BYTES = 2_000_000


class CompanySourceError(ValueError):
    """A source response or format could not be safely imported."""


@dataclass(frozen=True, slots=True)
class CompanySourceBatch:
    provider: str
    readme_url: str
    repository_url: str
    license_name: str
    license_url: str
    fetched_at: datetime
    body_sha256: str
    source_file_sha: str | None
    snapshot_path: Path
    records: tuple[CompanyEvidenceRecord, ...]


@dataclass(frozen=True, slots=True)
class SkippedCompanySource:
    provider: str
    repository_url: str
    reason: str
    imported_records: int = 0


def parse_spanish_top_tech_readme(text: str) -> tuple[CompanyEvidenceRecord, ...]:
    """Parse the source's published, per-company aggregate tables, not raw submissions."""

    run_date = _source_last_run(text)
    population_context = _spanish_top_tech_context(text)
    records: list[CompanyEvidenceRecord] = []
    for headers, rows, section in _markdown_tables(text):
        mapping = _toptech_header_mapping(headers)
        if mapping is None:
            continue
        for cells in rows:
            if len(cells) < len(headers):
                continue
            name, linkedin_url = _linked_text(cells[mapping["company"]])
            if not name:
                continue
            source_urls = _markdown_urls(cells[mapping["source"]]) if "source" in mapping else []
            jobs_urls = _markdown_urls(cells[mapping["jobs"]]) if "jobs" in mapping else []
            career_url = next((url for url in jobs_urls if _is_http_url(url)), None)
            base = _parse_money_k(cells[mapping["base"]])
            total = _parse_money_k(cells[mapping["total"]]) if "total" in mapping else None
            sample_size = _parse_integer(cells[mapping["sample_size"]]) if "sample_size" in mapping else None
            report_period = _cell_text(cells[mapping["reported"]]) if "reported" in mapping else None
            share_text = _cell_text(cells[mapping["share"]]) if "share" in mapping else None
            share_match = re.search(r"(?P<percent>\d+(?:\.\d+)?)\s*%\s*(?:\((?P<count>\d+)\))?", share_text or "")
            metric = _toptech_metric(headers[mapping["base"]])
            high_compensation = base >= 60_000 if base is not None else None
            source_key = normalize_company_name(name)
            if source_key is None:
                continue
            evidence = {
                "compensation": {
                    "metric": metric,
                    "base_annual_eur": _decimal_json(base),
                    "total_compensation_annual_eur": _decimal_json(total),
                    "currency": "EUR",
                    "period": "year",
                    "sample_size": sample_size,
                    "observation_period": report_period or None,
                    "population": population_context,
                    "high_compensation_evidence": high_compensation,
                    "at_60k_share": (
                        float(share_match.group("percent"))
                        if share_match is not None
                        else None
                    ),
                    "at_60k_count": (
                        int(share_match.group("count"))
                        if share_match is not None and share_match.group("count")
                        else None
                    ),
                    "table_section": section,
                    "source_run_date": run_date,
                    "source_evidence_urls": source_urls,
                    "career_page_url": career_url,
                    "linkedin_url": linkedin_url,
                },
                "career_page_url": career_url,
            }
            records.append(
                CompanyEvidenceRecord(
                    provider=SPANISH_TOP_TECH,
                    evidence_type=CompanyEvidenceType.COMPENSATION,
                    source_key=source_key,
                    company_name=name,
                    source_url=SPANISH_TOP_TECH_README,
                    external_identifier=linkedin_url,
                    structured_data=evidence,
                    raw_metadata={
                        "repository": SPANISH_TOP_TECH_REPOSITORY,
                        "license": SPANISH_TOP_TECH_LICENSE,
                        "license_url": SPANISH_TOP_TECH_LICENSE_URL,
                        "readme_url": SPANISH_TOP_TECH_README,
                        "source_run_date": run_date,
                        "third_party_data_notice": (
                            "The source repository says underlying Levels.fyi submissions are not covered by its data license; "
                            "no Levels.fyi pages were fetched by this importer."
                        ),
                    },
                )
            )
    if not records:
        raise CompanySourceError("Spanish Top Tech README contained no recognized company compensation table.")
    _reject_duplicate_source_keys(SPANISH_TOP_TECH, records)
    return tuple(records)


def parse_manfred_public_salary_readme(text: str) -> tuple[CompanyEvidenceRecord, ...]:
    """Parse the company/name-to-careers-URL table; no salary amounts are inferred."""

    records: list[CompanyEvidenceRecord] = []
    for headers, rows, _section in _markdown_tables(text):
        mapping = _manfred_header_mapping(headers)
        if mapping is None:
            continue
        for cells in rows:
            if len(cells) < len(headers):
                continue
            name, _company_url = _linked_text(cells[mapping["company"]])
            if not name:
                continue
            careers = [url for url in _markdown_urls(cells[mapping["url"]]) if _is_http_url(url)]
            source_key = normalize_company_name(name)
            if source_key is None:
                continue
            records.append(
                CompanyEvidenceRecord(
                    provider=MANFRED_PUBLIC_SALARY,
                    evidence_type=CompanyEvidenceType.PUBLIC_SALARY,
                    source_key=source_key,
                    company_name=name,
                    source_url=MANFRED_README,
                    structured_data={
                        "public_salary": True,
                        "public_salary_context": (
                            "Manfred's directory identifies the company as publishing salary ranges in job offers; "
                            "the directory does not publish a numeric range, sample size, or observation period."
                        ),
                        "career_page_url": careers[0] if careers else None,
                        "career_page_urls": careers,
                    },
                    raw_metadata={
                        "repository": MANFRED_REPOSITORY,
                        "license": MANFRED_LICENSE,
                        "license_url": MANFRED_LICENSE_URL,
                        "readme_url": MANFRED_README,
                    },
                )
            )
    if not records:
        raise CompanySourceError("Manfred README contained no recognized public-salary company table.")
    _reject_duplicate_source_keys(MANFRED_PUBLIC_SALARY, records)
    return tuple(records)


def refresh_company_source_snapshots(
    *,
    snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR,
    offline: bool = False,
    client: httpx.Client | None = None,
) -> tuple[tuple[CompanySourceBatch, ...], tuple[SkippedCompanySource, ...]]:
    """Fetch exactly two small READMEs on explicit refresh; offline mode replays saved files."""

    specs = (
        (
            SPANISH_TOP_TECH,
            "spanish-top-tech-companies",
            SPANISH_TOP_TECH_README,
            SPANISH_TOP_TECH_REPOSITORY,
            SPANISH_TOP_TECH_LICENSE,
            SPANISH_TOP_TECH_LICENSE_URL,
            parse_spanish_top_tech_readme,
        ),
        (
            MANFRED_PUBLIC_SALARY,
            "companies-with-public-salary",
            MANFRED_README,
            MANFRED_REPOSITORY,
            MANFRED_LICENSE,
            MANFRED_LICENSE_URL,
            parse_manfred_public_salary_readme,
        ),
    )
    owned_client = client is None and not offline
    active_client = client
    if owned_client:
        active_client = httpx.Client(
            timeout=httpx.Timeout(20.0),
            headers={"Accept": "text/plain", "User-Agent": "AI-Job-Hunter/0.1 (company evidence refresh)"},
        )
    batches: list[CompanySourceBatch] = []
    try:
        for provider, snapshot_name, url, repository, license_name, license_url, parser in specs:
            snapshot_path = snapshot_dir / f"{snapshot_name}.README.md"
            manifest_path = snapshot_dir / f"{snapshot_name}.manifest.json"
            file_sha: str | None = None
            if offline:
                if not snapshot_path.is_file():
                    raise CompanySourceError(f"Offline source snapshot is missing: {snapshot_path}")
                body_bytes = snapshot_path.read_bytes()
                if manifest_path.is_file():
                    saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    file_sha = saved_manifest.get("source_file_sha")
                    fetched_at = _parse_datetime(saved_manifest.get("fetched_at")) or datetime.fromtimestamp(
                        snapshot_path.stat().st_mtime, UTC
                    )
                else:
                    fetched_at = datetime.fromtimestamp(snapshot_path.stat().st_mtime, UTC)
            else:
                if active_client is None:
                    raise CompanySourceError("No HTTP client is available for online company source refresh.")
                body_parts: list[bytes] = []
                body_size = 0
                with active_client.stream("GET", url) as response:
                    response.raise_for_status()
                    file_sha = response.headers.get("x-github-content-sha")
                    for chunk in response.iter_bytes():
                        body_size += len(chunk)
                        if body_size > MAX_README_BYTES:
                            raise CompanySourceError(
                                f"Source README exceeded the {MAX_README_BYTES}-byte safety limit."
                            )
                        body_parts.append(chunk)
                body_bytes = b"".join(body_parts)
                fetched_at = datetime.now(UTC)
            try:
                body = body_bytes.decode("utf-8-sig")
            except UnicodeDecodeError as error:
                raise CompanySourceError(f"{provider} README is not valid UTF-8.") from error
            records = parser(body)
            digest = hashlib.sha256(body_bytes).hexdigest()
            if not offline:
                snapshot_dir.mkdir(parents=True, exist_ok=True)
                snapshot_path.write_bytes(body_bytes)
                manifest = {
                    "provider": provider,
                    "repository_url": repository,
                    "readme_url": url,
                    "license": license_name,
                    "license_url": license_url,
                    "fetched_at": fetched_at.isoformat(),
                    "source_file_sha": file_sha,
                    "sha256": digest,
                    "company_records": len(records),
                }
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
            batches.append(
                CompanySourceBatch(
                    provider=provider,
                    readme_url=url,
                    repository_url=repository,
                    license_name=license_name,
                    license_url=license_url,
                    fetched_at=fetched_at,
                    body_sha256=digest,
                    source_file_sha=file_sha,
                    snapshot_path=snapshot_path,
                    records=records,
                )
            )
    finally:
        if owned_client and active_client is not None:
            active_client.close()
    skipped = (
        SkippedCompanySource(
            provider=REMOTE_ES,
            repository_url=REMOTE_ES_REPOSITORY,
            reason=REMOTE_ES_SKIP_REASON,
        ),
    )
    return tuple(batches), skipped


def _markdown_tables(text: str) -> list[tuple[list[str], list[list[str]], str | None]]:
    lines = text.splitlines()
    tables: list[tuple[list[str], list[list[str]], str | None]] = []
    section: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if line.startswith("## "):
            section = _cell_text(line[3:])
        if not line.startswith("|"):
            index += 1
            continue
        headers = _split_markdown_row(line)
        if not headers or not any(cell.strip() for cell in headers):
            index += 1
            continue
        rows: list[list[str]] = []
        next_index = index + 1
        while next_index < len(lines) and lines[next_index].strip().startswith("|"):
            row = _split_markdown_row(lines[next_index].strip())
            if row and not all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in row):
                rows.append(row)
            next_index += 1
        tables.append((headers, rows, section))
        index = next_index
    return tables


def _split_markdown_row(line: str) -> list[str]:
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|"):
        value = value[:-1]
    return [cell.strip() for cell in value.split("|")]


def _toptech_header_mapping(headers: list[str]) -> dict[str, int] | None:
    normalized = [_cell_text(header).casefold() for header in headers]
    company = _find_header(normalized, lambda item: item in {"company", "empresa"})
    base = _find_header(normalized, lambda item: "base" in item and ("median" in item or "avg" in item or "average" in item))
    total = _find_header(normalized, lambda item: "total" in item and ("comp" in item or "compensation" in item))
    samples = _find_header(normalized, lambda item: item in {"engineers", "employees", "sample size", "samples"})
    reported = _find_header(normalized, lambda item: "reported" in item or "observation period" in item)
    source = _find_header(normalized, lambda item: item == "source" or item.startswith("source "))
    jobs = _find_header(normalized, lambda item: item in {"jobs", "careers", "career page", "open roles"})
    share = _find_header(normalized, lambda item: "60k" in item or item == "share")
    if None in (company, base, samples):
        return None
    result: dict[str, int] = {"company": company, "base": base, "sample_size": samples}
    for key, value in (("total", total), ("reported", reported), ("source", source), ("jobs", jobs), ("share", share)):
        if value is not None:
            result[key] = value
    return result


def _manfred_header_mapping(headers: list[str]) -> dict[str, int] | None:
    normalized = [_cell_text(header).casefold() for header in headers]
    company = _find_header(normalized, lambda item: item in {"empresa", "company"})
    url = _find_header(normalized, lambda item: item in {"url", "careers url", "career page", "jobs"})
    if company is None or url is None:
        return None
    return {"company": company, "url": url}


def _find_header(headers: list[str], predicate) -> int | None:
    return next((index for index, header in enumerate(headers) if predicate(header)), None)


def _toptech_metric(header: str) -> str:
    normalized = _cell_text(header).casefold()
    if "median" in normalized:
        return "median"
    if "average" in normalized or re.search(r"\bavg\b", normalized):
        return "average"
    return "unknown"


def _cell_text(cell: str) -> str:
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", cell)
    value = re.sub(r"<https?://[^>]+>", "", value)
    return re.sub(r"\s+", " ", value).strip().strip("`*_ ")


def _linked_text(cell: str) -> tuple[str, str | None]:
    match = re.search(r"\[([^\]]+)\]\((https?://[^)]+)\)", cell)
    if match:
        return _cell_text(match.group(1)), match.group(2).strip()
    plain = _cell_text(cell)
    if plain in {"—", "-", ""}:
        return "", None
    return plain, None


def _markdown_urls(cell: str) -> list[str]:
    return [url.rstrip(".,;") for url in re.findall(r"https?://[^\s)>\]]+", cell)]


def _is_http_url(url: str) -> bool:
    return urlsplit(url).scheme in {"http", "https"} and bool(urlsplit(url).hostname)


def _parse_money_k(cell: str) -> Decimal | None:
    value = _cell_text(cell).replace("€", "").replace("EUR", "").strip()
    if not value or value in {"—", "-", "n/a", "unknown"}:
        return None
    multiplier = Decimal("1000") if value.casefold().endswith("k") else Decimal("1")
    if value.casefold().endswith("k"):
        value = value[:-1].strip()
    value = value.replace(",", ".")
    try:
        number = Decimal(value) * multiplier
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _decimal_json(value: Decimal | None) -> int | float | None:
    if value is None:
        return None
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _parse_integer(cell: str) -> int | None:
    match = re.search(r"\d+", _cell_text(cell).replace(",", ""))
    return int(match.group(0)) if match else None


def _source_last_run(text: str) -> str | None:
    match = re.search(r"last run\s+(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE)
    return match.group(1) if match else None


def _spanish_top_tech_context(text: str) -> str:
    paragraphs = [
        re.sub(r"\s+", " ", paragraph.strip())
        for paragraph in re.split(r"\n\s*\n", text)
        if paragraph.strip() and not paragraph.strip().startswith("<!--")
    ]
    introduction = next((item for item in paragraphs if not item.startswith("#")), "")
    experience = re.search(r"\b(?P<years>\d+)(?:\+| or more)?\s+years?\b", text, re.IGNORECASE)
    experience_context = f"{experience.group('years')}+ years" if experience else "experienced"
    return (
        f"Spain-based software engineers with {experience_context} of experience; per-company "
        "gross annual EUR base and total compensation aggregates, with source-reported sample and period. "
        f"See {SPANISH_TOP_TECH_REPOSITORY} and its methodology."
    )


def _reject_duplicate_source_keys(provider: str, records: list[CompanyEvidenceRecord]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for record in records:
        if record.source_key in seen:
            duplicates.add(record.source_key)
        seen.add(record.source_key)
    if duplicates:
        names = ", ".join(sorted(duplicates))
        raise CompanySourceError(f"{provider} contains duplicate normalized company rows: {names}.")


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
