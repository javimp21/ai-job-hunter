"""Extract named people with a stated role from a company's own public HTML pages.

Only what the page literally states is returned: a name and a role that sit
next to each other (team/about pages), schema.org Person data, or an article
author. Nothing is guessed: no emails are composed, no profile URLs are
built, and a LinkedIn URL is kept only when the page itself links to it.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from ai_job_hunter.contact_discovery.matching import canonical_linkedin_profile_url
from ai_job_hunter.models.contact import ContactType

MAX_PEOPLE_PER_PAGE = 25
_SOCIAL_LABELS = frozenset(
    {"linkedin", "twitter", "x", "github", "email", "e-mail", "mail", "website", "web", "instagram",
     "bluesky", "mastodon", "medium", "blog", "in"}
)
_NAME_STOPWORDS = frozenset(
    {"team", "our", "meet", "the", "about", "us", "engineering", "product", "design", "careers", "career",
     "join", "we", "are", "and", "company", "people", "leadership", "management", "board", "advisors",
     "investors", "culture", "values", "mission", "contact", "jobs", "blog", "news", "press", "legal",
     "privacy", "terms", "cookies", "read", "more", "learn", "view", "all", "see", "hiring", "open",
     "roles", "positions", "departments", "equipo", "nosotros", "quienes", "somos", "empresa", "nuestro",
     "inicio", "home", "login", "sign", "get", "started", "request", "demo", "pricing", "solutions"}
)
_NAME_PARTICLES = frozenset({"de", "del", "la", "las", "los", "van", "von", "da", "di", "dos", "der", "den", "le"})

_ROLE_ENGINEERING_MANAGER = re.compile(
    r"\bengineering manager\b|\bhead of (?:engineering|technology|platform|software|backend)\b"
    r"|\b(?:director|vp|vice president)(?: of)? (?:of )?engineering\b|\bcto\b|\bchief technology officer\b"
    r"|\bresponsable de (?:ingenier[ií]a|tecnolog[ií]a|desarrollo)\b|\bjefe de (?:ingenier[ií]a|desarrollo)\b"
    r"|\bdirector (?:t[eé]cnico|de (?:ingenier[ií]a|tecnolog[ií]a))\b|\bmanager de (?:ingenier[ií]a|desarrollo)\b"
    r"|\bdevelopment manager\b|\bsoftware manager\b",
    re.IGNORECASE,
)
_ROLE_FOUNDER = re.compile(r"\bco-?founder\b|\bfounder\b|\bceo\b|\bfundador[a]?\b|\bchief executive\b", re.IGNORECASE)
_ROLE_TALENT = re.compile(r"\btalent\b|\brecruit|\bpeople (?:ops|operations|partner|&)|\bhr\b|\bhuman resources\b|\bselecci[oó]n\b", re.IGNORECASE)
_ROLE_ENGINEER = re.compile(
    r"\bengineer\b|\bdeveloper\b|\bprogrammer\b|\barchitect\b|\bsre\b|\bdevops\b|\btech(?:nical)? lead\b"
    r"|\blead (?:engineer|developer|backend|software)\b|\bstaff\b.*\bengineer|\bingenier[oa]\b|\bdesarrollador[a]?\b"
    r"|\bsoftware\b|\bbackend\b|\bback-end\b|\bplatform\b|\bdata scientist\b|\bml\b|\bmachine learning\b",
    re.IGNORECASE,
)
_ANY_ROLE = re.compile(
    r"\bmanager\b|\bdirector\b|\bhead of\b|\blead\b|\bofficer\b|\bdesigner\b|\banalyst\b|\bconsultant\b"
    r"|\bpartner\b|\bmarketing\b|\bsales\b|\bproduct\b|\bsupport\b|\bfinance\b|\blegal\b|\boperations\b",
    re.IGNORECASE,
)
_SEPARATORS = (" — ", " – ", " | ", " · ", " - ", ", ")


@dataclass(frozen=True, slots=True)
class PersonCandidate:
    name: str
    role: str | None
    contact_type: ContactType
    quote: str
    source_url: str
    evidence_type: str  # team_page | json_ld | github_profile
    linkedin_url: str | None = None
    email: str | None = None
    topic: str | None = None
    topic_url: str | None = None
    profile_url: str | None = None  # a link on the same site to the person's own page


@dataclass(slots=True)
class ParsedPage:
    url: str
    language: str | None = None
    people: list[PersonCandidate] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)  # (absolute url, anchor text)
    github_orgs: list[str] = field(default_factory=list)
    article_title: str | None = None
    article_authors: list[str] = field(default_factory=list)


def classify_role(role: str | None) -> ContactType | None:
    """Map a stated role to a contact type; None when the text is not a role we care about."""

    if not role or len(role) > 90:
        return None
    if _ROLE_ENGINEERING_MANAGER.search(role):
        return ContactType.ENGINEERING_MANAGER
    if _ROLE_FOUNDER.search(role):
        return ContactType.FOUNDER
    if _ROLE_TALENT.search(role):
        return ContactType.TALENT if re.search(r"talent", role, re.IGNORECASE) else ContactType.RECRUITER
    if _ROLE_ENGINEER.search(role):
        return ContactType.ENGINEER
    if _ANY_ROLE.search(role):
        return ContactType.OTHER
    return None


def looks_like_name(text: str) -> bool:
    value = " ".join(text.split())
    if not value or len(value) > 50 or any(character.isdigit() for character in value):
        return False
    if classify_role(value) is not None:
        return False
    tokens = value.split(" ")
    if not 2 <= len(tokens) <= 4:
        return False
    for index, token in enumerate(tokens):
        cleaned = token.replace("'", "").replace("’", "").replace("-", "").replace(".", "")
        if not cleaned or not cleaned.isalpha():
            return False
        if token.casefold() in _NAME_STOPWORDS:
            return False
        if token.casefold() in _NAME_PARTICLES and 0 < index < len(tokens) - 1:
            continue
        if not token[0].isupper():
            return False
    return True


def _split_name_and_role(text: str) -> tuple[str, str] | None:
    """Handle "Jane Doe — Engineering Manager" and "Engineering Manager, Jane Doe" in one node."""

    if len(text) > 120:
        return None
    for separator in _SEPARATORS:
        if separator not in text:
            continue
        left, _, right = text.partition(separator)
        left, right = left.strip(), right.strip()
        if looks_like_name(left) and classify_role(right) is not None:
            return left, right
        if looks_like_name(right) and classify_role(left) is not None:
            return right, left
    return None


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.language: str | None = None
        self.events: list[tuple[str, str, str]] = []  # (kind, value, extra)
        self.json_ld: list[str] = []
        self.meta_authors: list[str] = []
        self.title: str | None = None
        self._skip = 0
        self._in_json_ld = False
        self._json_buffer: list[str] = []
        self._anchor_href: str | None = None
        self._anchor_label: str = ""
        self._anchor_text: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): (value or "") for key, value in attrs}
        tag = tag.casefold()
        if tag == "html" and values.get("lang"):
            self.language = values["lang"].split("-")[0].casefold()
        elif tag == "script":
            if values.get("type", "").casefold() == "application/ld+json":
                self._in_json_ld = True
                self._json_buffer = []
            else:
                self._skip += 1
        elif tag in {"style", "noscript", "template", "svg"}:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta" and values.get("name", "").casefold() == "author" and values.get("content"):
            self.meta_authors.append(values["content"].strip())
        elif tag == "a" and values.get("href"):
            self._flush_anchor()
            self._anchor_href = values["href"].strip()
            self._anchor_label = " ".join(
                value for value in (values.get("aria-label", ""), values.get("title", "")) if value
            )
            self._anchor_text = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "script":
            if self._in_json_ld:
                self._in_json_ld = False
                self.json_ld.append("".join(self._json_buffer))
            elif self._skip:
                self._skip -= 1
        elif tag in {"style", "noscript", "template", "svg"} and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag == "a":
            self._flush_anchor()

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self._json_buffer.append(data)
            return
        if self._skip:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self._in_title:
            self.title = (self.title + " " + text) if self.title else text
            return
        if self._anchor_href is not None:
            self._anchor_text.append(text)
        self.events.append(("text", text, ""))

    def _flush_anchor(self) -> None:
        if self._anchor_href is None:
            return
        label = " ".join(self._anchor_text).strip()
        self.events.append(("link", self._anchor_href, f"{label} {self._anchor_label}".strip()))
        self._anchor_href = None
        self._anchor_text = []

    def close(self) -> None:
        super().close()
        self._flush_anchor()


def parse_page(url: str, html: str, *, company_domain: str | None = None) -> ParsedPage:
    parser = _PageParser()
    parser.feed(html)
    parser.close()
    page = ParsedPage(url=url, language=parser.language)

    for kind, value, label in parser.events:
        if kind != "link":
            continue
        absolute = urljoin(url, value)
        parts = urlsplit(absolute)
        if parts.scheme.casefold() in {"http", "https"} and parts.hostname:
            page.links.append((absolute, label))
            org = _github_org(parts)
            if org and org not in page.github_orgs:
                page.github_orgs.append(org)

    people: dict[str, PersonCandidate] = {}
    for candidate in _json_ld_people(parser.json_ld, url):
        people.setdefault(candidate.name.casefold(), candidate)
    for candidate in _card_people(parser.events, url, company_domain):
        people.setdefault(candidate.name.casefold(), candidate)
    page.people = list(people.values())[:MAX_PEOPLE_PER_PAGE]
    page.article_title, page.article_authors = _article(parser.json_ld, parser.meta_authors, parser.title)
    return page


def _github_org(parts) -> str | None:
    host = (parts.hostname or "").casefold()
    if host not in {"github.com", "www.github.com"}:
        return None
    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) != 1:
        return None
    name = segments[0]
    if name.casefold() in {"features", "about", "pricing", "login", "join", "sponsors", "orgs", "topics", "marketplace"}:
        return None
    return name if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", name) else None


def _card_people(
    events: list[tuple[str, str, str]], page_url: str, company_domain: str | None
) -> list[PersonCandidate]:
    # Text nodes of social-label anchors ("LinkedIn") are not content; keep real text only.
    texts: list[tuple[int, str]] = []
    for index, (kind, value, _label) in enumerate(events):
        if kind == "text" and value.casefold() not in _SOCIAL_LABELS:
            texts.append((index, value))
    found: list[PersonCandidate] = []
    used: set[int] = set()
    for position, (event_index, text) in enumerate(texts):
        if position in used:
            continue
        pair = _split_name_and_role(text)
        name_pos = role_pos = position
        if pair is not None:
            name, role = pair
        elif looks_like_name(text) and position + 1 < len(texts) and _is_role_line(texts[position + 1][1]):
            name, role = text, texts[position + 1][1]
            role_pos = position + 1
        elif _is_role_line(text) and position + 1 < len(texts) and looks_like_name(texts[position + 1][1]) and (
            position == 0 or not looks_like_name(texts[position - 1][1])
        ):
            name, role = texts[position + 1][1], text
            name_pos = position + 1
        else:
            continue
        contact_type = classify_role(role)
        if contact_type is None:
            continue
        used.update({name_pos, role_pos})
        start = texts[min(name_pos, role_pos)][0]
        end_text = max(name_pos, role_pos)
        stop = texts[end_text + 1][0] if end_text + 1 < len(texts) else len(events)
        linkedin, email, profile = _links_in_card(
            events, start, stop, name, page_url, company_domain
        )
        found.append(
            PersonCandidate(
                name=" ".join(name.split()),
                role=" ".join(role.split()),
                contact_type=contact_type,
                quote=f"{' '.join(name.split())} — {' '.join(role.split())}"[:240],
                source_url=page_url,
                evidence_type="team_page",
                linkedin_url=linkedin,
                email=email,
                profile_url=profile,
            )
        )
    return found


def _is_role_line(text: str) -> bool:
    return len(text) <= 90 and classify_role(text) is not None


def _links_in_card(
    events: list[tuple[str, str, str]],
    start: int,
    stop: int,
    name: str,
    page_url: str,
    company_domain: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Links between the person's first text node and the next unrelated text node.

    A LinkedIn link is attributed only when its anchor is labelled LinkedIn or
    wraps the person's name, so a neighbour's image-only link is never reused.
    """

    linkedin: str | None = None
    email: str | None = None
    profile: str | None = None
    first_name = name.split()[0].casefold()
    for kind, value, label in events[start:stop]:
        if kind != "link":
            continue
        folded = label.casefold()
        absolute = urljoin(page_url, value)
        if absolute.casefold().startswith("mailto:"):
            address = absolute[7:].split("?")[0].strip().casefold()
            domain = address.rpartition("@")[2]
            if (
                company_domain
                and "@" in address
                and (domain == company_domain or domain.endswith("." + company_domain))
                and email is None
            ):
                email = address
            continue
        canonical = canonical_linkedin_profile_url(absolute)
        if canonical is not None:
            named = name.casefold() in folded or first_name in folded
            labelled = "linkedin" in folded
            # A bare "LinkedIn" label can belong to the neighbouring card (link-before-name
            # layouts), so it must also be consistent with this person's name.
            if linkedin is None and (named or (labelled and _slug_mentions_name(canonical, name))):
                linkedin = canonical
            continue
        host = (urlsplit(absolute).hostname or "").casefold()
        if (
            profile is None
            and company_domain
            and (host == company_domain or host.endswith("." + company_domain))
            and (name.casefold() in folded)
        ):
            profile = absolute
    return linkedin, email, profile


def _ascii(value: str) -> str:
    return "".join(
        character for character in unicodedata.normalize("NFKD", value) if not unicodedata.combining(character)
    ).casefold()


def _slug_mentions_name(linkedin_url: str, name: str) -> bool:
    slug = _ascii(urlsplit(linkedin_url).path)
    return any(len(token) >= 3 and token in slug for token in re.split(r"[^a-z]+", _ascii(name)))


def _json_ld_nodes(blocks: list[str]) -> list[dict]:
    nodes: list[dict] = []

    def visit(value: object) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            nodes.append(value)
            visit(value.get("@graph"))

    for block in blocks:
        try:
            visit(json.loads(block))
        except ValueError:
            continue
    return nodes


def _types(node: dict) -> set[str]:
    raw = node.get("@type")
    values = raw if isinstance(raw, list) else [raw]
    return {str(value).casefold() for value in values if value}


def _json_ld_people(blocks: list[str], page_url: str) -> list[PersonCandidate]:
    people: list[PersonCandidate] = []
    for node in _json_ld_nodes(blocks):
        candidates = []
        if "person" in _types(node):
            candidates.append(node)
        author = node.get("author")
        for item in author if isinstance(author, list) else [author]:
            if isinstance(item, dict) and "person" in _types(item):
                candidates.append(item)
        for person in candidates:
            name = person.get("name")
            role = person.get("jobTitle")
            if not isinstance(name, str) or not isinstance(role, str) or not looks_like_name(name):
                continue
            contact_type = classify_role(role)
            if contact_type is None:
                continue
            same_as = person.get("sameAs")
            same_as = same_as if isinstance(same_as, list) else [same_as]
            linkedin = next(
                (canonical_linkedin_profile_url(item) for item in same_as if isinstance(item, str)
                 and canonical_linkedin_profile_url(item)),
                None,
            )
            people.append(
                PersonCandidate(
                    name=" ".join(name.split()),
                    role=" ".join(role.split()),
                    contact_type=contact_type,
                    quote=f"{' '.join(name.split())} — {' '.join(role.split())}"[:240],
                    source_url=page_url,
                    evidence_type="json_ld",
                    linkedin_url=linkedin,
                )
            )
    return people


def _article(blocks: list[str], meta_authors: list[str], title: str | None) -> tuple[str | None, list[str]]:
    for node in _json_ld_nodes(blocks):
        if _types(node) & {"article", "blogposting", "newsarticle", "techarticle"}:
            headline = node.get("headline")
            author = node.get("author")
            names = [
                item.get("name") if isinstance(item, dict) else item
                for item in (author if isinstance(author, list) else [author])
            ]
            names = [" ".join(name.split()) for name in names if isinstance(name, str) and looks_like_name(name)]
            if isinstance(headline, str) and headline.strip() and names:
                return " ".join(headline.split())[:200], names
    names = [" ".join(name.split()) for name in meta_authors if looks_like_name(name)]
    if names and title:
        return " ".join(title.split())[:200], names
    return None, []
