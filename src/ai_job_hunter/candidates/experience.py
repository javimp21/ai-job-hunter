"""Evidence-backed experience years, separate from title seniority and semantic fit."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from html.parser import HTMLParser

EXPERIENCE_POLICY_VERSION = "explicit-experience-v1"


class ExperienceStrength(StrEnum):
    MANDATORY = "MANDATORY"
    PREFERRED = "PREFERRED"
    AMBIGUOUS = "AMBIGUOUS"


class ExperienceExpressionKind(StrEnum):
    FLOOR = "FLOOR"
    RANGE = "RANGE"
    UPPER_BOUND = "UPPER_BOUND"


class ExperienceOutcome(StrEnum):
    MEETS = "MEETS"
    STRETCH = "STRETCH"
    INCOMPATIBLE = "INCOMPATIBLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ExperienceRequirement:
    strength: ExperienceStrength
    kind: ExperienceExpressionKind
    minimum_years: Decimal | None
    maximum_years: Decimal | None
    minimum_exclusive: bool
    maximum_exclusive: bool
    upper_plus: bool
    scope_specific: bool
    clause: str
    source_line: int

    def display(self) -> str:
        if self.kind is ExperienceExpressionKind.RANGE:
            return f"{_number(self.minimum_years)}–{_number(self.maximum_years)}{'+' if self.upper_plus else ''} years"
        if self.kind is ExperienceExpressionKind.UPPER_BOUND:
            return f"{'less than' if self.maximum_exclusive else 'at most'} {_number(self.maximum_years)} years"
        return f"{'more than' if self.minimum_exclusive else 'minimum'} {_number(self.minimum_years)}{'+' if self.upper_plus else ''} years"


@dataclass(frozen=True, slots=True)
class ExperienceAssessment:
    outcome: ExperienceOutcome
    mandatory: tuple[ExperienceRequirement, ...]
    preferred: tuple[ExperienceRequirement, ...]
    shortfall_years: Decimal | None
    reason: str
    ambiguous: tuple[ExperienceRequirement, ...] = ()

    @property
    def requirement_display(self) -> str:
        parts = [f"mandatory: {item.display()}" for item in self.mandatory]
        parts.extend(f"preferred: {item.display()}" for item in self.preferred)
        parts.extend(f"unclear: {item.display()}" for item in self.ambiguous)
        return "; ".join(dict.fromkeys(parts)) or "No explicit experience-years requirement found"

    @property
    def evidence(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            f"line {item.source_line}: {item.clause}" for item in (*self.mandatory, *self.preferred, *self.ambiguous)
        ))

    @property
    def public_summary(self) -> str:
        """Only public requirements and generic concerns, never candidate years/gaps."""
        labels = {
            ExperienceOutcome.MEETS: "numeric requirement met",
            ExperienceOutcome.STRETCH: "stretch — experience requirement not met",
            ExperienceOutcome.INCOMPATIBLE: "outside configured experience range",
            ExperienceOutcome.UNKNOWN: "compatibility UNKNOWN",
        }
        return f"{self.requirement_display}; {labels[self.outcome]}"


def assess_experience(
    requirements: tuple[ExperienceRequirement, ...],
    candidate_years: Decimal | None,
    *,
    floor_shortfall_tolerance: Decimal = Decimal("2"),
    range_shortfall_tolerance: Decimal = Decimal("1"),
) -> ExperienceAssessment:
    mandatory = tuple(r for r in requirements if r.strength is ExperienceStrength.MANDATORY)
    preferred = tuple(r for r in requirements if r.strength is ExperienceStrength.PREFERRED)
    ambiguous = tuple(r for r in requirements if r.strength is ExperienceStrength.AMBIGUOUS)
    if not mandatory or candidate_years is None:
        return ExperienceAssessment(
            ExperienceOutcome.UNKNOWN, mandatory, preferred, None,
            "Explicit mandatory experience compatibility is unknown.", ambiguous,
        )
    outcomes: list[ExperienceOutcome] = []
    shortfalls: list[Decimal] = []
    for requirement in mandatory:
        low, high = requirement.minimum_years, requirement.maximum_years
        if low is not None and high is not None and low > high:
            outcomes.append(ExperienceOutcome.UNKNOWN)
            continue
        if requirement.kind is ExperienceExpressionKind.UPPER_BOUND:
            assert high is not None
            exceeds = candidate_years >= high if requirement.maximum_exclusive else candidate_years > high
            outcomes.append(ExperienceOutcome.INCOMPATIBLE if exceeds else ExperienceOutcome.MEETS)
            continue
        assert low is not None
        shortfall = max(Decimal(0), low - candidate_years)
        # An exclusive bound cannot be met at equality. Preserve that fact
        # without inventing an extra year of mandatory experience.
        unmet = shortfall > 0 or (requirement.minimum_exclusive and candidate_years == low)
        tolerance = range_shortfall_tolerance if requirement.kind is ExperienceExpressionKind.RANGE else floor_shortfall_tolerance
        if unmet:
            shortfalls.append(shortfall)
            permitted = shortfall < tolerance if requirement.minimum_exclusive else shortfall <= tolerance
            outcomes.append(ExperienceOutcome.STRETCH if permitted else ExperienceOutcome.INCOMPATIBLE)
        elif requirement.scope_specific:
            # Total career years cannot prove years in a named technology/role.
            outcomes.append(ExperienceOutcome.UNKNOWN)
        else:
            outcomes.append(ExperienceOutcome.MEETS)
    if ExperienceOutcome.INCOMPATIBLE in outcomes:
        outcome = ExperienceOutcome.INCOMPATIBLE
    elif ExperienceOutcome.STRETCH in outcomes:
        outcome = ExperienceOutcome.STRETCH
    elif ExperienceOutcome.UNKNOWN in outcomes or ambiguous:
        outcome = ExperienceOutcome.UNKNOWN
    else:
        outcome = ExperienceOutcome.MEETS
    shortfall = max(shortfalls) if shortfalls else None
    reason = {
        ExperienceOutcome.MEETS: "Explicit numeric experience requirements are met; other constraints still apply.",
        ExperienceOutcome.STRETCH: "Mandatory experience is unmet but within the configured stretch tolerance; human review required.",
        ExperienceOutcome.INCOMPATIBLE: "Mandatory experience is outside the configured floor/range tolerance.",
        ExperienceOutcome.UNKNOWN: "Experience compatibility is unknown or specific experience scope is unverified.",
    }[outcome]
    return ExperienceAssessment(outcome, mandatory, preferred, shortfall, reason, ambiguous)


_WORDS = {word: Decimal(value) for value, words in enumerate((
    ("zero", "cero"), ("one", "un", "una"), ("two", "dos"), ("three", "tres"),
    ("four", "cuatro"), ("five", "cinco"), ("six", "seis"), ("seven", "siete"),
    ("eight", "ocho"), ("nine", "nueve"), ("ten", "diez"),
)) for word in words}
_N = r"(?:\d+(?:[.,]\d+)?|" + "|".join(_WORDS) + r")"
MAX_PLAUSIBLE_YEARS = 40
_UNIT = r"(?:years?|yrs?|años?)\b"
_RANGE = re.compile(rf"(?<!\w)(?:between\s+|entre\s+)?(?P<low>{_N})\s*(?:{_UNIT}\s*)?(?:[-–—]|to\b|through\b|and\b|a\b|y\b)\s*(?P<high>{_N})\s*(?P<plus>\+)?\s*{_UNIT}", re.I)
_UPPER = re.compile(rf"(?P<cue>less\s+than|fewer\s+than|under|no\s+more\s+than|at\s+most|up\s+to|menos\s+de|como\s+m[aá]ximo|hasta|<=|≤|<)\s*(?P<value>{_N})\s*{_UNIT}", re.I)
_FLOOR = re.compile(rf"(?P<cue>at\s+least|minimum(?:\s+of)?|more\s+than|over|al\s+menos|m[ií]nimo(?:\s+de)?|m[aá]s\s+de|>=|≥|>)\s*(?P<value>{_N})\s*(?P<plus>\+)?\s*{_UNIT}", re.I)
_SINGLE = re.compile(rf"(?<!\w)(?P<value>{_N})\s*(?P<plus>\+)?\s*{_UNIT}", re.I)
_OPTIONAL = re.compile(r"\b(?:preferred|desired|nice\s+to\s+have|desirable|deseable|valorable|bonus|a\s+plus|ideally|se\s+valorara)\b", re.I)
_EXPERIENCE = re.compile(r"\b(?:experience|experiencia|professional|profesional|as\s+(?:a|an)\s+\w+)\b", re.I)
_ALTERNATIVE = re.compile(r"\b(?:or\s+equivalent|or\s+a\s+degree|o\s+equivalente)\b", re.I)


def extract_experience_requirements(description: str | None) -> tuple[ExperienceRequirement, ...]:
    if not description:
        return ()
    requirements: list[ExperienceRequirement] = []
    section = "unknown"
    for line_number, raw in enumerate(_block_text(description).splitlines(), 1):
        line = raw.strip().lstrip("•*-–— ")
        if not line:
            continue
        heading, separator, remainder = line.partition(":")
        heading_kind = _section_kind(heading if separator else line)
        if heading_kind:
            section = heading_kind
            if not separator or not remainder.strip():
                continue
            line = remainder.strip()
        # Do not split decimal numbers or silently combine separate bullets.
        for clause in re.split(r"[;!?]\s*|(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚ])", line):
            if section == "company" or _incidental(clause):
                # Employer history/perks are not applicant evidence and must
                # not mask a separate, explicit qualification later on.
                continue
            matches = _expressions(clause)
            if not matches:
                continue
            if section == "preferred" or _OPTIONAL.search(_ascii(clause)):
                strength = ExperienceStrength.PREFERRED
            elif _ALTERNATIVE.search(clause) or (len(matches) > 1 and re.search(r"\b(?:or|o)\b", clause, re.I)):
                strength = ExperienceStrength.AMBIGUOUS
            elif section == "mandatory" or _EXPERIENCE.search(clause):
                strength = ExperienceStrength.MANDATORY
            else:
                strength = ExperienceStrength.AMBIGUOUS
            for match, kind, low, high, low_exclusive, high_exclusive, plus in matches:
                tail = clause[match.end():]
                scope = bool(re.match(
                    r"\s*(?:(?:of\s+|de\s+)?experience\s+|de\s+experiencia\s+)?"
                    r"(?:as\s+(?:a|an)|in\s+(?!total\b)|with\s+|using\s+|en\s+|con\s+)"
                    r"|\s*(?:of\s+|de\s+)(?!(?:professional|profesional|relevant|overall|general|work|experience|experiencia)\b)"
                    r"\w+(?:\s+\w+){0,3}\s+(?:experience|experiencia)\b",
                    tail, re.I,
                ))
                requirements.append(ExperienceRequirement(
                    strength, kind, low, high, low_exclusive, high_exclusive,
                    plus, scope, clause.strip(), line_number,
                ))
    return tuple(requirements)


def _expressions(clause: str) -> list[tuple]:
    found: list[tuple] = []
    occupied: list[tuple[int, int]] = []
    for pattern, kind in ((_RANGE, ExperienceExpressionKind.RANGE), (_UPPER, ExperienceExpressionKind.UPPER_BOUND), (_FLOOR, ExperienceExpressionKind.FLOOR), (_SINGLE, ExperienceExpressionKind.FLOOR)):
        for match in pattern.finditer(clause):
            if any(match.start() < end and match.end() > start for start, end in occupied):
                continue
            occupied.append((match.start(), match.end()))
            values = match.groupdict()
            cue = _ascii(re.sub(r"\s+", " ", values.get("cue", "")))
            low = _parse(values["low"] if kind is ExperienceExpressionKind.RANGE else values["value"]) if kind is not ExperienceExpressionKind.UPPER_BOUND else None
            high = _parse(values["high"] if kind is ExperienceExpressionKind.RANGE else values["value"]) if kind is not ExperienceExpressionKind.FLOOR else None
            if any(value is not None and value > MAX_PLAUSIBLE_YEARS for value in (low, high)):
                continue  # "more than 160 years of history" is the employer's age, not a requirement
            found.append((match, kind, low, high, cue in {"more than", "over", "mas de", ">"}, cue in {"less than", "fewer than", "under", "menos de", "<"}, bool(values.get("plus"))))
    return sorted(found, key=lambda entry: entry[0].start())


def _parse(value: str) -> Decimal:
    value = value.casefold().replace(",", ".")
    return _WORDS[value] if value in _WORDS else Decimal(value)


def _ascii(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


def _section_kind(value: str) -> str | None:
    value = re.sub(r"[^a-z0-9]+", " ", _ascii(value)).strip()
    if value in {"nice to have", "preferred", "preferred qualifications", "preferred experience", "desired", "desired qualifications", "desired experience", "additional qualifications", "additional experience", "bonus points", "deseable", "deseables", "requisitos deseables", "valorable"}:
        return "preferred"
    if value in {"requirements", "qualifications", "minimum qualifications", "required qualifications", "required experience", "mandatory experience", "must have", "what you ll need", "what we re looking for", "what we are looking for", "skills you ll need to bring", "what you ll bring", "what youll bring", "your qualifications", "your profile", "who you are", "requisitos", "requisitos obligatorios", "experiencia requerida", "experiencia obligatoria", "tu perfil", "lo que buscamos", "que buscamos"}:
        return "mandatory"
    if value in {"about us", "about the company", "benefits", "what we offer", "acerca de nosotros", "sobre nosotros", "sobre la empresa", "beneficios", "que ofrecemos"}:
        return "company"
    if value in {"about the role", "the role", "job description", "responsibilities", "what you ll do", "about you", "responsabilidades"}:
        return "unknown"
    return None


def _incidental(clause: str) -> bool:
    text = clause.strip()
    starts_with_employer = re.match(
        r"^(?:our\s+|the\s+|this\s+|nuestra\s+|la\s+)?"
        r"(?:company|business|startup|product|team|empresa|equipo)\b",
        text,
        re.I,
    )
    if starts_with_employer and not re.search(
        r"\b(?:requires?|seeks?|looking\s+for|needs?|requiere|exige|busca|necesita)\b",
        text,
        re.I,
    ):
        return True
    return bool(re.search(
        r"\b(?:founded|established|launched|fundada|fundado|combined\s+(?:team\s+)?experience|team\s+tenure)\b"
        r"|^(?:we\s+(?:have|bring|offer)|somos|llevamos)\b.{0,100}\b(?:years?|años?)\b"
        r"|^(?:we\s+are|we['’]re)\s+(?:a\s+|an\s+|the\s+)?(?:company|business|startup|team|market\s+leader)\b.{0,100}\b(?:years?|años?)\b"
        r"|^(?:with|con)\b.{0,140}\b(?:we\s+are|somos|(?:is|are)\s+(?:a\s+)?(?:market\s+)?leaders?)\b"
        r"|\b(?:years?|años?)\s+(?:as\s+(?:a\s+)?market\s+leaders?|como\s+l[ií]der(?:es)?\s+del\s+mercado)\b",
        text, re.I,
    ))


class _TextBlocks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "li", "h1", "h2", "h3", "h4", "section", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        self.handle_starttag(tag, [])

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _block_text(value: str) -> str:
    if not re.search(r"</?[a-z][^>]*>", value, re.I):
        return value
    parser = _TextBlocks()
    parser.feed(value)
    parser.close()
    return "".join(parser.parts)


def _number(value: Decimal | None) -> str:
    return format(value.normalize(), "f") if value is not None else "?"
