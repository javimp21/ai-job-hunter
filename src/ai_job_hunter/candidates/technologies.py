"""Small explicit technology vocabulary used by the deterministic pre-filter."""

from __future__ import annotations

import re
from collections.abc import Iterable


# Extend this table as tests and real source text show a need. Matching is by
# whole terms so, for example, Java does not match JavaScript.
_TECHNOLOGY_ALIASES: dict[str, tuple[str, ...]] = {
    "java": (r"\bjava\b",),
    "spring boot": (r"\bspring\s+boot\b",),
    "spring": (r"\bspring\b(?!\s+boot\b)",),
    "kotlin": (r"\bkotlin\b",),
    "python": (r"\bpython\b",),
    "go": (r"\bgolang\b",),
    "typescript": (r"\btypescript\b",),
    "javascript": (r"\bjavascript\b",),
    "node.js": (r"\bnode(?:\.js|js)\b",),
    "node": (r"\bnode\b(?!\s*\.)",),
    "react": (r"\breact\b",),
    "angular": (r"\bangular\b",),
    "aws": (r"\baws\b|\bamazon\s+web\s+services\b",),
    "azure": (r"\bazure\b",),
    "gcp": (r"\bgcp\b|\bgoogle\s+cloud\s+platform\b",),
    "docker": (r"\bdocker\b",),
    "kubernetes": (r"\bkubernetes\b|\bk8s\b",),
    "postgresql": (r"\bpostgres(?:ql)?\b",),
    "mysql": (r"\bmysql\b",),
    "redis": (r"\bredis\b",),
    "kafka": (r"\bkafka\b",),
    "rabbitmq": (r"\brabbitmq\b|\brabbit\s*mq\b",),
    "c++": (r"(?<!\w)c\+\+(?!\w)",),
    "c#": (r"(?<!\w)c#(?!\w)",),
    ".net": (r"(?<!\w)\.net(?!\w)",),
}
_COMPILED_ALIASES = {
    canonical: tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)
    for canonical, patterns in _TECHNOLOGY_ALIASES.items()
}
_GO_WORD = re.compile(r"\bgo\b", re.IGNORECASE)
_GO_DESCRIPTOR_AFTER = re.compile(
    r"^\s+(?:language|programming|developer|engineer|services?|backend)\b|"
    r"^\s+is\s+(?:required|a\s+must)\b",
    re.IGNORECASE,
)
_GO_DESCRIPTOR_BEFORE = re.compile(
    r"\b(?:written\s+in|built\s+with|using|experience\s+with)\s*$",
    re.IGNORECASE,
)
_REQUIRED_BEFORE = re.compile(
    r"\b(?:required|must\s+(?:have|possess)|mandatory|essential|"
    r"proficiency\s+in|strong\s+experience\s+with)\b",
    re.IGNORECASE,
)
_REQUIRED_AFTER = re.compile(
    r"^\s*(?:is\s+|are\s+)?(?:explicitly\s+)?required\b|"
    r"^\s*(?:is\s+)?a\s+must\b",
    re.IGNORECASE,
)

TECHNOLOGY_FAMILY: dict[str, str] = {
    "java": "language",
    "kotlin": "language",
    "python": "language",
    "go": "language",
    "typescript": "language",
    "javascript": "language",
    "c++": "language",
    "c#": "language",
    "node.js": "javascript_runtime",
    "node": "javascript_runtime",
    "react": "javascript_framework",
    "angular": "javascript_framework",
    "spring": "jvm_framework",
    "spring boot": "jvm_framework",
    "aws": "cloud",
    "azure": "cloud",
    "gcp": "cloud",
    "docker": "container_platform",
    "kubernetes": "container_platform",
    "postgresql": "relational_database",
    "mysql": "relational_database",
    "redis": "key_value_database",
    "kafka": "message_broker",
    "rabbitmq": "message_broker",
    ".net": "dotnet",
}


def normalize_technology(value: str) -> str:
    """Map a known alias to a canonical term; normalize unknown skills gently."""

    normalized = " ".join(value.casefold().strip().split())
    for canonical, compiled_patterns in _COMPILED_ALIASES.items():
        if any(pattern.fullmatch(normalized) for pattern in compiled_patterns):
            return canonical
    alias_lookup = {
        "golang": "go",
        "nodejs": "node.js",
        "postgres": "postgresql",
        "k8s": "kubernetes",
        "google cloud platform": "gcp",
        "amazon web services": "aws",
    }
    return alias_lookup.get(normalized, normalized)


def normalize_technology_list(values: Iterable[str]) -> frozenset[str]:
    return frozenset(normalize_technology(value) for value in values if value.strip())


def extract_job_technologies(
    title: str,
    description: str | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return explicitly mentioned and explicitly required technology names.

    A word ``Go`` is counted in a job title, or in description when the nearby
    text clearly identifies the language. Unlabeled prose such as "go and build"
    is intentionally ignored.
    """

    description_text = description or ""
    found: set[str] = set()
    required: set[str] = set()
    for canonical, patterns in _COMPILED_ALIASES.items():
        title_matches = [match for pattern in patterns for match in pattern.finditer(title)]
        description_matches = [
            match for pattern in patterns for match in pattern.finditer(description_text)
        ]
        if canonical == "go":
            title_matches.extend(
                match
                for match in _GO_WORD.finditer(title)
                if _is_contextual_go(title, match.start(), match.end())
            )
            description_matches.extend(
                match
                for match in _GO_WORD.finditer(description_text)
                if _is_contextual_go(description_text, match.start(), match.end())
            )
        if title_matches or description_matches:
            found.add(canonical)
        if any(_is_explicitly_required(description_text, match.start(), match.end())
               for match in description_matches):
            required.add(canonical)
    return tuple(sorted(found)), tuple(sorted(required))


def _is_explicitly_required(text: str, start: int, end: int) -> bool:
    line_start = text.rfind("\n", 0, start) + 1
    prefix = text[max(line_start, start - 120) : start]
    # Periods inside names such as Node.js and .NET are not sentence breaks.
    prefix = re.sub(r"(?<=\w)\.(?=\w)", "", prefix)
    clause_break = max(prefix.rfind("."), prefix.rfind("!"), prefix.rfind("?"), prefix.rfind(";"))
    if _REQUIRED_BEFORE.search(prefix[clause_break + 1 :]):
        return True

    line_end = text.find("\n", end)
    suffix = text[end : end + 60 if line_end < 0 else min(line_end, end + 60)]
    return _REQUIRED_AFTER.search(suffix) is not None


def _is_contextual_go(text: str, start: int, end: int) -> bool:
    line_start = text.rfind("\n", 0, start) + 1
    prefix = text[max(line_start, start - 100) : start]
    clause_break = max(prefix.rfind("."), prefix.rfind("!"), prefix.rfind("?"), prefix.rfind(";"))
    before = prefix[clause_break + 1 :]
    if _REQUIRED_BEFORE.search(before) or _GO_DESCRIPTOR_BEFORE.search(before):
        return True
    line_end = text.find("\n", end)
    after = text[end : end + 50 if line_end < 0 else min(line_end, end + 50)]
    return _GO_DESCRIPTOR_AFTER.search(after) is not None
