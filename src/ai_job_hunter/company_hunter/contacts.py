"""Find verifiable people at a company from sources the company itself publishes.

Sources: the company website's team/about pages, engineering-blog author data
(JSON-LD / meta author) and the public members of a GitHub organization that
the company's own site links to. Pages are fetched with ``PoliteFetcher``
(robots.txt, spacing, page budget). Nothing is stored unless a name *and* a
stated role were found on a public page; emails only when the page links a
``mailto:`` address on the company's own domain. LinkedIn is never fetched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_job_hunter.company_hunter.fetching import FetchRefused, PoliteFetcher
from ai_job_hunter.company_hunter.people import (
    ParsedPage,
    PersonCandidate,
    classify_role,
    looks_like_name,
    parse_page,
)
from ai_job_hunter.contact_discovery.matching import canonical_linkedin_profile_url
from ai_job_hunter.deduplication.normalization import extract_company_domain
from ai_job_hunter.models import Company, CompanyLead
from ai_job_hunter.models.contact import ContactType
from ai_job_hunter.services.outreach_persistence import OutreachPersistenceError, create_contact

GITHUB_API_HOST = "api.github.com"
MAX_GITHUB_MEMBERS = 6
MAX_TEAM_PAGES = 3
MAX_BLOG_POSTS = 2
_KEPT_TYPES = frozenset(
    {
        ContactType.ENGINEER,
        ContactType.ENGINEERING_MANAGER,
        ContactType.FOUNDER,
        ContactType.TALENT,
        ContactType.RECRUITER,
    }
)
_TEAM_LINK = re.compile(
    r"team|equipo|people|leadership|about|nosotros|quienes|qui[eé]nes|who.?we.?are|company|empresa|engineering",
    re.IGNORECASE,
)
_NOT_TEAM_LINK = re.compile(r"career|jobs?\b|empleo|trabaja|privacy|terms|legal|cookies|press|login|signin|pricing", re.IGNORECASE)
_BLOG_LINK = re.compile(r"blog|engineering|tech|ingenier", re.IGNORECASE)
_POST_PATH = re.compile(r"/(?:blog|posts?|articles?|engineering|noticias|articulos)/[^/]+", re.IGNORECASE)


@dataclass(slots=True)
class ContactDiscoveryResult:
    company_id: UUID
    website: str | None = None
    pages_fetched: int = 0
    api_calls: int = 0
    found: int = 0
    created: int = 0
    existing: int = 0
    refused: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def stored_nothing(self) -> bool:
        return self.created == 0


def discover_contacts(
    session: Session,
    company_id: UUID,
    *,
    fetcher: PoliteFetcher,
    now: datetime | None = None,
) -> ContactDiscoveryResult:
    """Fetch the company's public pages and store verifiable contacts."""

    company = session.get(Company, company_id)
    result = ContactDiscoveryResult(company_id=company_id)
    if company is None:
        result.notes.append("company not found")
        return result
    website = company.website_url or session.scalar(
        select(CompanyLead.website_url).where(
            CompanyLead.company_id == company_id, CompanyLead.website_url.is_not(None)
        )
    )
    result.website = website
    domain = extract_company_domain(website)
    if not website or not domain:
        result.notes.append("no company website is known; nothing to read")
        return result
    observed = (now or datetime.now(UTC)).isoformat(timespec="seconds")

    pages: list[ParsedPage] = []
    github_orgs: list[str] = []

    def read(url: str) -> ParsedPage | None:
        try:
            final_url, html = fetcher.get_html(url)
        except FetchRefused as error:
            result.refused.append((url, str(error)))
            return None
        page = parse_page(final_url, html, company_domain=domain)
        pages.append(page)
        for org in page.github_orgs:
            if org not in github_orgs:
                github_orgs.append(org)
        return page

    home = read(website if "://" in website else f"https://{website}")
    if home is not None:
        for url in _team_links(home, domain)[:MAX_TEAM_PAGES]:
            read(url)
        blog_index = next(iter(_blog_links(home, domain)), None)
        if blog_index is not None:
            index_page = read(blog_index)
            if index_page is not None:
                for post_url in _post_links(index_page, domain)[:MAX_BLOG_POSTS]:
                    read(post_url)

    candidates: dict[str, PersonCandidate] = {}
    topics: dict[str, tuple[str, str]] = {}
    languages: dict[str, str | None] = {}
    for page in pages:
        for person in page.people:
            if person.contact_type not in _KEPT_TYPES:
                continue
            key = person.name.casefold()
            existing = candidates.get(key)
            if existing is None or (existing.linkedin_url is None and person.linkedin_url):
                candidates[key] = person
                languages[key] = page.language
        if page.article_title:
            for author in page.article_authors:
                topics.setdefault(author.casefold(), (page.article_title, page.url))

    if github_orgs:
        for person in _github_people(github_orgs[0], fetcher, result):
            key = person.name.casefold()
            if key not in candidates:
                candidates[key] = person
                languages[key] = None

    result.pages_fetched = fetcher.pages_fetched
    result.api_calls = fetcher.api_calls
    result.found = len(candidates)
    if not candidates:
        result.notes.append("no verifiable people with a stated role were found; nothing stored")
        return result

    for key, person in candidates.items():
        topic = topics.get(key)
        language = languages.get(key)
        evidence: dict[str, object] = {
            "evidence_type": person.evidence_type,
            "quote": person.quote,
            "observed_at": observed,
        }
        if language in {"es", "en"}:
            evidence["language"] = language
        topic_title, topic_url = (person.topic, person.topic_url) if person.topic else (topic or (None, None))
        if topic_title and topic_url:
            evidence["topic"] = topic_title[:240]
            evidence["topic_url"] = topic_url[:240]
        try:
            created = create_contact(
                session,
                company_id=company_id,
                name=person.name,
                contact_type=person.contact_type,
                title=person.role,
                linkedin_url=person.linkedin_url,
                email=person.email,
                source_provider="github_org" if person.evidence_type == "github_profile" else "company_site",
                external_id=f"{person.source_url}#{person.name.casefold()}"[:512],
                source_url=person.source_url,
                evidence=evidence,
            )
        except OutreachPersistenceError as error:
            result.notes.append(f"{person.name}: not stored ({error})")
            continue
        if created.created:
            result.created += 1
        else:
            result.existing += 1
    session.flush()
    return result


def _same_site(url: str, domain: str) -> bool:
    host = (urlsplit(url).hostname or "").casefold().rstrip(".")
    return host == domain or host.endswith("." + domain) or host == "www." + domain


def _team_links(page: ParsedPage, domain: str) -> list[str]:
    scored: list[tuple[int, str]] = []
    for url, label in page.links:
        if not _same_site(url, domain):
            continue
        path = urlsplit(url).path
        text = f"{label} {path}"
        if _NOT_TEAM_LINK.search(text) or not _TEAM_LINK.search(text):
            continue
        priority = 0 if re.search(r"team|equipo|people|leadership", text, re.IGNORECASE) else 1
        scored.append((priority, url))
    seen: dict[str, int] = {}
    for priority, url in sorted(scored):
        seen.setdefault(url.split("#")[0], priority)
    return list(seen)


def _blog_links(page: ParsedPage, domain: str) -> list[str]:
    links: list[str] = []
    for url, label in page.links:
        if not _same_site(url, domain):
            continue
        path = urlsplit(url).path
        if _BLOG_LINK.search(f"{label} {path}") and not _TEAM_LINK.search(path.replace("engineering", "")):
            if url.split("#")[0] not in links:
                links.append(url.split("#")[0])
    return links


def _post_links(index: ParsedPage, domain: str) -> list[str]:
    posts: list[str] = []
    for url, _label in index.links:
        if _same_site(url, domain) and _POST_PATH.search(urlsplit(url).path) and url != index.url:
            clean = url.split("#")[0]
            if clean not in posts:
                posts.append(clean)
    return posts


def _github_people(org: str, fetcher: PoliteFetcher, result: ContactDiscoveryResult) -> list[PersonCandidate]:
    """Public members of a GitHub org the company site links to; only profiles that state a role."""

    allowed = frozenset({GITHUB_API_HOST})
    org_path = quote(org, safe="")
    try:
        members = fetcher.get_public_json(
            f"https://{GITHUB_API_HOST}/orgs/{org_path}/public_members?per_page={MAX_GITHUB_MEMBERS}",
            allowed_hosts=allowed,
        )
    except FetchRefused as error:
        result.refused.append((f"github org {org}", str(error)))
        return []
    if not isinstance(members, list):
        return []
    people: list[PersonCandidate] = []
    for member in members[:MAX_GITHUB_MEMBERS]:
        login = member.get("login") if isinstance(member, dict) else None
        if not isinstance(login, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", login):
            continue
        try:
            profile = fetcher.get_public_json(
                f"https://{GITHUB_API_HOST}/users/{quote(login, safe='')}", allowed_hosts=allowed
            )
        except FetchRefused as error:
            result.refused.append((f"github user {login}", str(error)))
            break
        if not isinstance(profile, dict):
            continue
        name, bio = profile.get("name"), profile.get("bio")
        if not isinstance(name, str) or not looks_like_name(name) or not isinstance(bio, str):
            continue
        bio = " ".join(bio.split())
        contact_type = classify_role(bio)
        if contact_type not in _KEPT_TYPES:
            continue
        blog = profile.get("blog")
        linkedin = canonical_linkedin_profile_url(blog) if isinstance(blog, str) else None
        html_url = profile.get("html_url") if isinstance(profile.get("html_url"), str) else f"https://github.com/{login}"
        people.append(
            PersonCandidate(
                name=" ".join(name.split()),
                role=bio,
                contact_type=contact_type,
                quote=f"GitHub profile of public member of {org}: {bio}"[:240],
                source_url=html_url,
                evidence_type="github_profile",
                linkedin_url=linkedin,
            )
        )
    return people
