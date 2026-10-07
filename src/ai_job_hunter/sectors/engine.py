"""Declarative role-family classifier driven by a sector template (see docs/SECTOR_TEMPLATES_DESIGN.md).

A template is data: named word sets, named regular expressions, the compound spellings to expand, and an ORDERED list
of rules. The first rule whose condition holds decides the result. Conditions are small boolean trees over the
normalized title words and, where needed, the raw title:

    {"tokens_any": ["@engineering_job", "devops"]}   at least one of these words (``@name`` expands a named set)
    {"tokens_all": ["forward", "deployed"]}          all of these words
    {"regex": "business_development"}                a named regex (or an inline pattern) found in the raw title
    {"all": [...]} / {"any": [...]} / {"not": {...}} / {"true": true}

The engine returns plain strings (``fit``, ``family``, ``reason``); the prefilter turns them into its own types.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_job_hunter.deduplication.normalization import normalize_job_title

SECTORS_DIR = Path(__file__).resolve().parent / "templates"
FITS = {"TARGET", "POTENTIALLY_RELEVANT", "NON_TARGET", "UNKNOWN"}


@dataclass(frozen=True, slots=True)
class RoleFamilyResult:
    fit: str
    family: str
    reason: str


class Compound(BaseModel):
    """Two or more words that mean one word ("back end" and "backend"), expanded in the token set."""

    model_config = ConfigDict(extra="forbid")

    parts: list[str]
    word: str
    expand_back: bool = True  # also add the parts when the compound word is written as one


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    when: dict[str, Any]
    fit: str
    family: str
    reason: str
    focus: str = ""


class StackProfile(BaseModel):
    """Technologies that raise or lower a posting's review priority (omit for sectors without a tech stack)."""

    model_config = ConfigDict(extra="forbid")

    core: list[str]  # the candidate's own stack: small bonus
    adjacent: list[str] = Field(default_factory=list)  # neighbouring stack: neutral
    penalized: list[str] = Field(default_factory=list)  # a different discipline: penalty
    core_bonus: int = 5
    penalty: int = 15
    required_penalty: int = 10  # extra when the posting REQUIRES technologies outside core and adjacent
    core_label: str
    penalized_label: str


class RubricSpec(BaseModel):
    """The questions Jev answers about a posting, in this sector's words."""

    model_config = ConfigDict(extra="forbid")

    version: str
    question_types: dict[str, str]
    questions: dict[str, str]
    score_criteria: dict[str, list[str]]


class SectorTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    stack: StackProfile | None = None
    rubric: RubricSpec | None = None
    # Lowest priority that alerts a REVIEW offer in this sector; unset means the global setting. Jev's answers are
    # calibrated with software, so a sector whose scores run lower starts with a lower bar until real feedback exists.
    alert_min_priority: int | None = Field(default=None, ge=0, le=100)
    sets: dict[str, list[str]] = Field(default_factory=dict)
    regexes: dict[str, str] = Field(default_factory=dict)
    compounds: list[Compound] = Field(default_factory=list)
    rules: list[Rule]


class SectorTemplateError(ValueError):
    """The template is malformed (unknown set, bad condition, bad fit...)."""


Predicate = Callable[[frozenset[str], str], bool]


class CompiledTemplate:
    def __init__(self, template: SectorTemplate) -> None:
        self.template = template
        self._sets = {name: frozenset(word.casefold() for word in words) for name, words in template.sets.items()}
        self._regexes = {name: re.compile(pattern, re.IGNORECASE) for name, pattern in template.regexes.items()}
        self._compounds = [
            (frozenset(item.parts), item.word, item.expand_back) for item in template.compounds
        ]
        self._rules: list[tuple[Rule, Predicate]] = []
        for rule in template.rules:
            if rule.fit not in FITS:
                raise SectorTemplateError(f"rule {rule.id}: unknown fit {rule.fit!r}")
            self._rules.append((rule, self._condition(rule.when, rule.id)))

    # -- compilation ---------------------------------------------------------------------------------------
    def _words(self, entries: list[str], rule_id: str) -> frozenset[str]:
        words: set[str] = set()
        for entry in entries:
            if entry.startswith("@"):
                if entry[1:] not in self._sets:
                    raise SectorTemplateError(f"rule {rule_id}: unknown set {entry!r}")
                words |= self._sets[entry[1:]]
            else:
                words.add(entry.casefold())
        return frozenset(words)

    def _condition(self, node: dict[str, Any], rule_id: str) -> Predicate:
        if len(node) != 1:
            raise SectorTemplateError(f"rule {rule_id}: a condition has exactly one key, got {sorted(node)}")
        ((key, value),) = node.items()
        if key == "true":
            return lambda tokens, title: True
        if key == "tokens_any":
            words = self._words(value, rule_id)
            return lambda tokens, title: not tokens.isdisjoint(words)
        if key == "tokens_all":
            words = self._words(value, rule_id)
            return lambda tokens, title: words <= tokens
        if key == "regex":
            pattern = self._regexes.get(value) or re.compile(value, re.IGNORECASE)
            return lambda tokens, title: pattern.search(title) is not None
        if key in {"all", "any"}:
            parts = [self._condition(child, rule_id) for child in value]
            combine = all if key == "all" else any
            return lambda tokens, title: combine(part(tokens, title) for part in parts)
        if key == "not":
            inner = self._condition(value, rule_id)
            return lambda tokens, title: not inner(tokens, title)
        raise SectorTemplateError(f"rule {rule_id}: unknown condition {key!r}")

    # -- evaluation ----------------------------------------------------------------------------------------
    def tokens(self, title: str) -> frozenset[str]:
        """Normalized title words plus both spellings of the compound role words."""

        normalized = normalize_job_title(title)
        tokens = set(normalized.tokens | normalized.seniority)
        for parts, word, expand_back in self._compounds:
            if parts <= tokens:
                tokens.add(word)
            elif expand_back and word in tokens:
                tokens |= parts
        return frozenset(tokens)

    def classify(self, title: str) -> RoleFamilyResult:
        tokens = self.tokens(title)
        for rule, predicate in self._rules:
            if predicate(tokens, title):
                return RoleFamilyResult(
                    rule.fit, rule.family, rule.reason.format(family=rule.family, focus=rule.focus)
                )
        raise SectorTemplateError(f"template {self.template.id}: no rule matched {title!r}; add a final catch-all rule")


def load_template(path: Path) -> CompiledTemplate:
    try:
        return CompiledTemplate(SectorTemplate.model_validate(json.loads(path.read_text(encoding="utf-8"))))
    except (OSError, ValueError) as error:
        raise SectorTemplateError(f"Cannot load sector template {path}: {error}") from error


@lru_cache(maxsize=8)
def get_template(sector_id: str) -> CompiledTemplate:
    return load_template(SECTORS_DIR / f"{sector_id}.json")


def classify_role_family(title: str, sector_id: str = "software") -> RoleFamilyResult:
    return get_template(sector_id).classify(title)
