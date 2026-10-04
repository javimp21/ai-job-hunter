"""Extract real people with a stated role from a company's own public HTML pages.

Order of trust: structured data first (JSON-LD ``Person``, ``author`` of an
article, schema.org microdata ``Person``), then explicit team/about *cards*:
the smallest element whose own text holds exactly one person-looking name next
to a recognised role. Navigation, menus, footers, headers outside the content
and product/marketing words never produce people, and cards are only read on
team/about-style pages (never on a home page). Nothing is guessed: no emails
are composed, no profile URLs are built, and a LinkedIn URL is kept only when
the card itself links to it.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from ai_job_hunter.company_hunter.relevance import assess_role
from ai_job_hunter.contact_discovery.matching import canonical_linkedin_profile_url
from ai_job_hunter.models.contact import ContactType

MAX_PEOPLE_PER_PAGE = 25
MAX_CARD_ENTRIES = 6
_SOCIAL_LABELS = frozenset(
    {"linkedin", "twitter", "x", "github", "email", "e-mail", "mail", "website", "web", "instagram",
     "bluesky", "mastodon", "medium", "blog", "in", "facebook", "youtube", "xing"}
)
_NAME_STOPWORDS = frozenset(
    {"team", "our", "meet", "the", "about", "us", "engineering", "product", "products", "design", "careers",
     "career", "join", "we", "are", "and", "company", "people", "leadership", "management", "board",
     "advisors", "investors", "culture", "values", "mission", "contact", "jobs", "blog", "news", "press",
     "legal", "privacy", "terms", "cookies", "read", "more", "learn", "view", "all", "see", "hiring", "open",
     "roles", "positions", "departments", "equipo", "nosotros", "quienes", "somos", "empresa", "nuestro",
     "inicio", "home", "login", "sign", "get", "started", "request", "demo", "pricing", "solutions",
     # product / navigation / marketing words
     "platform", "cloud", "data", "ai", "analytics", "intelligence", "assistant", "academy", "calculator",
     "gateway", "integration", "integrations", "migration", "overview", "connect", "customer", "customers",
     "business", "artificial", "marketing", "sales", "services", "service", "security", "governance",
     "partner", "partners", "providers", "resources", "documentation", "support", "community", "events",
     "webinars", "training", "certification", "download", "downloads", "free", "trial", "pricing", "plans",
     "industries", "industry", "finance", "healthcare", "retail", "government", "software", "tools", "tool",
     "api", "apis", "sdk", "developer", "developers", "engineer", "engineers", "manager", "managers",
     "director", "officer", "head", "lead", "founder", "founders", "chief", "president", "vice", "senior",
     "junior", "staff", "principal", "analyst", "designer", "recruiter", "talent", "global", "international",
     "política", "politica", "privacidad", "aviso", "cookie", "acerca", "producto", "productos", "soluciones",
     "servicios", "clientes", "recursos", "contacto", "carreras", "empleo", "noticias", "prensa"}
)
_NAME_PARTICLES = frozenset({"de", "del", "la", "las", "los", "van", "von", "da", "di", "dos", "der", "den", "le"})
_NAME_PREFIXES = frozenset({"dr", "dr.", "prof", "prof.", "mr", "mrs", "ms", "sra.", "sr.", "dra."})
_SEPARATORS = (" — ", " – ", " | ", " · ", " - ", ", ")
_TEAM_PATH = re.compile(
    r"team|equipo|people|leadership|management|about|acerca|nosotros|quienes|qui[eé]nes|who.?we.?are|company"
    r"|empresa|our.?story|founders|executive|gestion|f[uü]hrung|[uü]ber.?uns|equipe|[àa].?propos|chi.?siamo",
    re.IGNORECASE,
)
_BLOCK_TAGS = frozenset(
    {"div", "p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "ul", "ol", "section", "article", "table", "tr", "td",
     "th", "header", "footer", "nav", "main", "aside", "figure", "figcaption", "blockquote", "dl", "dt", "dd",
     "form", "body", "html", "details", "summary", "address", "hr", "br"}
)
_VOID_TAGS = frozenset({"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "source",
                        "track", "wbr", "param"})
_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "head", "title"})
_EXCLUDED_TAGS = frozenset({"nav", "footer", "aside", "menu", "dialog"})
_EXCLUDED_ROLES = frozenset({"navigation", "menu", "menubar", "banner", "contentinfo", "search", "complementary"})
_EXCLUDED_CLASS = re.compile(
    r"(?:^|[^a-z])(?:nav|navbar|navigation|menu|megamenu|mega-menu|footer|breadcrumb|breadcrumbs|dropdown|"
    r"cookie|cookies|sitemap|subnav|topbar|sidebar)(?:[^a-z]|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class PersonCandidate:
    name: str
    role: str | None
    contact_type: ContactType
    quote: str
    source_url: str
    evidence_type: str  # team_card | json_ld | microdata | github_profile
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
    links: list[tuple[str, str]] = field(default_factory=list)  # (absolute url, anchor text), page-wide
    github_orgs: list[str] = field(default_factory=list)
    article_title: str | None = None
    article_authors: list[str] = field(default_factory=list)
    cards_read: bool = False


def classify_role(role: str | None) -> ContactType | None:
    """Contact type of a stated role we target (engineering people, recruiters, C-level); else None."""

    assessment = assess_role(role)
    return assessment.contact_type if assessment else None


def is_team_page(url: str) -> bool:
    """Cards are read only on team/about-style pages, never on a home page."""

    path = urlsplit(url).path
    return bool(_TEAM_PATH.search(path))


def looks_like_name(text: str) -> bool:
    value = " ".join(text.split())
    if not value or len(value) > 50 or any(character.isdigit() for character in value):
        return False
    if assess_role(value) is not None:
        return False
    tokens = value.split(" ")
    if tokens and tokens[0].casefold() in _NAME_PREFIXES:
        tokens = tokens[1:]
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
        # ALL-CAPS words of 2-3 letters ("AI", "BI", "IT") are acronyms, not name parts.
        if token.isupper() and len(cleaned) <= 3:
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
        if looks_like_name(left) and assess_role(right) is not None:
            return left, right
        if looks_like_name(right) and assess_role(left) is not None:
            return right, left
    return None


# --------------------------------------------------------------------------------------
# Lightweight DOM


@dataclass(eq=False)
class _Node:
    tag: str
    attrs: dict[str, str]
    parent: "_Node | None" = None
    children: list["_Node | str"] = field(default_factory=list)
    excluded: bool = False

    def own_text(self) -> str:
        parts: list[str] = []

        def walk(node: "_Node") -> None:
            for child in node.children:
                if isinstance(child, str):
                    parts.append(child)
                elif child.tag not in _SKIP_TAGS:
                    walk(child)

        walk(self)
        return " ".join(" ".join(parts).split())

    def has_block_child(self) -> bool:
        def walk(node: "_Node") -> bool:
            return any(
                isinstance(child, _Node) and child.tag not in _SKIP_TAGS and (child.tag in _BLOCK_TAGS or walk(child))
                for child in node.children
            )

        return walk(self)


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("root", {})
        self.current = self.root
        self.language: str | None = None
        self.json_ld: list[str] = []
        self.meta_authors: list[str] = []
        self.title: str | None = None
        self._json_buffer: list[str] | None = None
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        values = {key.casefold(): (value or "") for key, value in attrs}
        if tag == "html" and values.get("lang"):
            self.language = values["lang"].split("-")[0].casefold()
        if tag == "script" and values.get("type", "").casefold() == "application/ld+json":
            self._json_buffer = []
            return
        if tag == "title":
            self._in_title = True
        if tag == "meta" and values.get("name", "").casefold() == "author" and values.get("content"):
            self.meta_authors.append(values["content"].strip())
        node = _Node(tag, values, parent=self.current)
        node.excluded = self.current.excluded or _is_excluded(node)
        self.current.children.append(node)
        if tag not in _VOID_TAGS:
            self.current = node

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.casefold() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "script" and self._json_buffer is not None:
            self.json_ld.append("".join(self._json_buffer))
            self._json_buffer = None
            return
        if tag == "title":
            self._in_title = False
        node = self.current
        while node is not self.root:
            if node.tag == tag:
                self.current = node.parent or self.root
                return
            node = node.parent or self.root

    def handle_data(self, data: str) -> None:
        if self._json_buffer is not None:
            self._json_buffer.append(data)
            return
        if self._in_title:
            text = " ".join(data.split())
            if text:
                self.title = (self.title + " " + text) if self.title else text
            return
        if data.strip():
            self.current.children.append(data)


def _is_excluded(node: _Node) -> bool:
    if node.tag in _EXCLUDED_TAGS:
        return True
    if node.attrs.get("role", "").casefold() in _EXCLUDED_ROLES:
        return True
    if _EXCLUDED_CLASS.search(f"{node.attrs.get('class', '')} {node.attrs.get('id', '')}"):
        return True
    if node.tag == "header":
        # A page header is chrome; a <header> inside the content (article/section/main) is not.
        ancestor = node.parent
        while ancestor is not None:
            if ancestor.tag in {"main", "article", "section"}:
                return False
            ancestor = ancestor.parent
        return True
    return False


def _walk(node: _Node):
    for child in node.children:
        if isinstance(child, _Node):
            yield child
            yield from _walk(child)


def parse_page(
    url: str, html: str, *, company_domain: str | None = None, allow_cards: bool | None = None
) -> ParsedPage:
    """Parse one page. ``allow_cards`` defaults to "this URL looks like a team/about page"."""

    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    page = ParsedPage(url=url, language=builder.language)
    cards = is_team_page(url) if allow_cards is None else allow_cards
    page.cards_read = cards

    menu_texts: set[str] = set()
    for node in _walk(builder.root):
        if node.tag != "a" or not node.attrs.get("href"):
            continue
        label = node.own_text()
        if node.excluded and label:
            menu_texts.add(label.casefold())
        # Links are used only to find the company's own team/blog pages, so menus count here.
        absolute = urljoin(url, node.attrs["href"].strip())
        parts = urlsplit(absolute)
        if parts.scheme.casefold() in {"http", "https"} and parts.hostname:
            page.links.append((absolute, label))
    # GitHub org links may live in the footer, which is the company's own, so look at every anchor.
    for node in _walk(builder.root):
        if node.tag == "a" and node.attrs.get("href"):
            parts = urlsplit(urljoin(url, node.attrs["href"].strip()))
            org = _github_org(parts)
            if org and org not in page.github_orgs:
                page.github_orgs.append(org)

    people: dict[str, PersonCandidate] = {}
    for candidate in _json_ld_people(builder.json_ld, url):
        people.setdefault(candidate.name.casefold(), candidate)
    for candidate in _microdata_people(builder.root, url):
        people.setdefault(candidate.name.casefold(), candidate)
    if cards:
        for candidate in _card_people(builder.root, url, company_domain, menu_texts):
            people.setdefault(candidate.name.casefold(), candidate)
    page.people = list(people.values())[:MAX_PEOPLE_PER_PAGE]
    page.article_title, page.article_authors = _article(builder.json_ld, builder.meta_authors, builder.title)
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


# --------------------------------------------------------------------------------------
# Cards


_Entry = tuple[str, _Node]


def _card_people(
    root: _Node, page_url: str, company_domain: str | None, menu_texts: set[str]
) -> list[PersonCandidate]:
    entries: dict[int, list[_Entry] | None] = {}
    found: list[PersonCandidate] = []
    consumed: set[int] = set()

    def collect(node: _Node) -> list[_Entry] | None:
        """Leaf-block texts of the subtree, or None once it holds too many to be a card."""

        if node.tag in _SKIP_TAGS or node.excluded:
            entries[id(node)] = []
            return []
        if not node.has_block_child():
            text = node.own_text()
            result: list[_Entry] | None = [(text, node)] if text and text.casefold() not in _SOCIAL_LABELS else []
            entries[id(node)] = result
            return result
        gathered: list[_Entry] | None = []
        direct = " ".join(child for child in node.children if isinstance(child, str)).split()
        if direct and " ".join(direct).casefold() not in _SOCIAL_LABELS:
            gathered.append((" ".join(direct), node))
        for child in node.children:
            if not isinstance(child, _Node):
                continue
            sub = collect(child)
            if sub is None or gathered is None:
                gathered = None
            else:
                gathered.extend(sub)
                if len(gathered) > MAX_CARD_ENTRIES:
                    gathered = None
        entries[id(node)] = gathered
        if any(isinstance(child, _Node) and id(child) in consumed for child in node.children):
            consumed.add(id(node))  # a smaller card inside already won; do not re-read it as a bigger one
        elif gathered:
            person = _person_in_card(node, gathered, page_url, company_domain, menu_texts)
            if person is not None:
                found.append(person)
                consumed.add(id(node))
        return gathered

    collect(root)
    return found


def _person_in_card(
    card: _Node, entries: list[_Entry], page_url: str, company_domain: str | None, menu_texts: set[str]
) -> PersonCandidate | None:
    if len(entries) < 1 or card.tag in {"body", "html", "root", "main"}:
        return None
    # A card never nests an already accepted card: callers mark consumed nodes; descendants are
    # visited first, so a smaller qualifying element wins.
    texts = [text for text, _node in entries]
    names = [index for index, text in enumerate(texts) if looks_like_name(text) and text.casefold() not in menu_texts]
    single = [index for index, text in enumerate(texts) if _split_name_and_role(text) is not None]
    name: str | None = None
    role: str | None = None
    if len(single) == 1 and len(names) <= 1:
        name, role = _split_name_and_role(texts[single[0]])  # type: ignore[misc]
    elif len(names) == 1:
        index = names[0]
        for neighbour in (index + 1, index - 1):
            if 0 <= neighbour < len(texts) and assess_role(texts[neighbour]) is not None:
                name, role = texts[index], texts[neighbour]
                break
    else:
        return None
    if name is None or role is None:
        return None
    assessment = assess_role(role)
    if assessment is None:
        return None
    # Another role-like entry that is not this person's role would make the card ambiguous
    # (e.g. a row of several people sharing one wrapper); require at most 2 roles.
    if sum(1 for text in texts if assess_role(text) is not None) > 2:
        return None
    linkedin, email, profile = _links_in_card(card, name, page_url, company_domain)
    clean_name = " ".join(name.split())
    clean_role = " ".join(role.split())
    return PersonCandidate(
        name=clean_name,
        role=clean_role,
        contact_type=assessment.contact_type,
        quote=f"{clean_name} — {clean_role}"[:240],
        source_url=page_url,
        evidence_type="team_card",
        linkedin_url=linkedin,
        email=email,
        profile_url=profile,
    )


def _links_in_card(
    card: _Node, name: str, page_url: str, company_domain: str | None
) -> tuple[str | None, str | None, str | None]:
    linkedin: str | None = None
    email: str | None = None
    profile: str | None = None
    linkedin_links = sum(
        1
        for node in _walk(card)
        if node.tag == "a" and canonical_linkedin_profile_url(urljoin(page_url, node.attrs.get("href", "")))
    )
    for node in _walk(card):
        if node.tag != "a" or not node.attrs.get("href"):
            continue
        label = f"{node.own_text()} {node.attrs.get('aria-label', '')} {node.attrs.get('title', '')}".casefold()
        absolute = urljoin(page_url, node.attrs["href"].strip())
        if absolute.casefold().startswith("mailto:"):
            address = absolute[7:].split("?")[0].strip().casefold()
            domain = address.rpartition("@")[2]
            if (
                company_domain and "@" in address and email is None
                and (domain == company_domain or domain.endswith("." + company_domain))
            ):
                email = address
            continue
        canonical = canonical_linkedin_profile_url(absolute)
        if canonical is not None:
            labelled = "linkedin" in label
            # Inside the person's own card a LinkedIn-labelled link (one per card) or a link whose
            # slug names the person is theirs; an unlabelled avatar link to a stranger is not.
            if linkedin is None and (_slug_mentions_name(canonical, name) or (labelled and linkedin_links == 1)):
                linkedin = canonical
            continue
        host = (urlsplit(absolute).hostname or "").casefold()
        if (
            profile is None and company_domain
            and (host == company_domain or host.endswith("." + company_domain))
            and name.casefold() in label
        ):
            profile = absolute
    return linkedin, email, profile


# --------------------------------------------------------------------------------------
# Structured data


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
            for key in ("@graph", "employee", "employees", "member", "members", "founder", "founders"):
                visit(value.get(key))

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


def _person_from_mapping(person: dict, page_url: str, evidence_type: str) -> PersonCandidate | None:
    name, role = person.get("name"), person.get("jobTitle")
    if not isinstance(name, str) or not isinstance(role, str) or not looks_like_name(name):
        return None
    assessment = assess_role(role)
    if assessment is None:
        return None
    same_as = person.get("sameAs")
    same_as = same_as if isinstance(same_as, list) else [same_as]
    linkedin = next(
        (canonical_linkedin_profile_url(item) for item in same_as
         if isinstance(item, str) and canonical_linkedin_profile_url(item)),
        None,
    )
    clean_name, clean_role = " ".join(name.split()), " ".join(role.split())
    return PersonCandidate(
        name=clean_name,
        role=clean_role,
        contact_type=assessment.contact_type,
        quote=f"{clean_name} — {clean_role}"[:240],
        source_url=page_url,
        evidence_type=evidence_type,
        linkedin_url=linkedin,
    )


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
            candidate = _person_from_mapping(person, page_url, "json_ld")
            if candidate is not None:
                people.append(candidate)
    return people


def _microdata_people(root: _Node, page_url: str) -> list[PersonCandidate]:
    people: list[PersonCandidate] = []
    for node in _walk(root):
        if node.excluded or "schema.org/person" not in node.attrs.get("itemtype", "").casefold():
            continue
        props: dict[str, str] = {}
        for child in _walk(node):
            prop = child.attrs.get("itemprop")
            if prop in {"name", "jobTitle"} and prop not in props:
                props[prop] = child.attrs.get("content") or child.own_text()
        candidate = _person_from_mapping(props, page_url, "microdata")
        if candidate is not None:
            people.append(candidate)
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
