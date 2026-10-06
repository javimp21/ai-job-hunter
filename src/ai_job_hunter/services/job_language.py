"""Spoken-language requirements of a posting, for a candidate who speaks only Spanish and English.

Two soft signals, never a rejection (they only lower the review priority):

* the posting asks for another language as a requirement ("fluent German", "Dutch required"), unless
  the wording marks it as optional ("German is a plus");
* the posting itself is written in another language (German, Dutch, French, a Nordic language), which
  almost always means the team works in it.
"""

from __future__ import annotations

import re

LANGUAGES = ("german", "dutch", "french", "swedish", "danish", "norwegian", "finnish", "italian", "portuguese")
_NAMES = "|".join(LANGUAGES)
_LEVEL = r"(?:fluent|fluency|proficien\w*|native|business[- ]level|business[- ]fluent|working knowledge|command|C1|C2|B2\+|mandatory|required|must|excellent|very good|strong|good|advanced)"
_REQUIRED_BEFORE = re.compile(rf"\b{_LEVEL}\b[^.;\n]{{0,40}}?\b({_NAMES})\b", re.IGNORECASE)
_REQUIRED_AFTER = re.compile(rf"\b({_NAMES})\b[^.;\n]{{0,30}}?\b(?:required|mandatory|fluent|fluency|proficien\w*|native|C1|C2|speaker)\b", re.IGNORECASE)
_OPTIONAL = re.compile(
    r"\b(?:plus|nice to have|advantage|asset|bonus|preferred|desirable|beneficial|appreciated|a plus|ideally|welcome|optional)\b",
    re.IGNORECASE,
)

# Frequent function words of each language; a text is "written in" a language when its words dominate
# the English ones by a wide margin.
_FUNCTION_WORDS = {
    "english": {"the", "and", "with", "you", "for", "our", "will", "are", "your", "have", "this", "that", "from", "team"},
    "german": {"und", "der", "die", "das", "mit", "für", "von", "sie", "wir", "ein", "eine", "nicht", "auf", "den", "zu"},
    "dutch": {"en", "het", "een", "van", "voor", "met", "wij", "je", "jij", "ons", "bij", "ook", "te", "naar", "zijn"},
    "french": {"et", "les", "des", "pour", "avec", "vous", "nous", "une", "dans", "sur", "votre", "notre", "est", "du"},
    "swedish": {"och", "att", "som", "för", "med", "vi", "är", "på", "du", "en", "ett", "av", "inom", "dig"},
    "danish": {"og", "til", "med", "som", "vi", "er", "på", "du", "en", "et", "af", "for", "dig", "hos"},
    "norwegian": {"og", "til", "med", "som", "vi", "er", "på", "du", "en", "et", "av", "for", "deg", "hos"},
    "finnish": {"ja", "on", "ei", "että", "kanssa", "meillä", "sinä", "olet", "työ", "tai", "myös", "joka"},
}
_WORD = re.compile(r"[a-zà-ÿäöåüß]+", re.IGNORECASE)
MIN_WORDS = 40


def required_foreign_language(description: str | None) -> str | None:
    """A spoken language the posting requires (not marked optional), or None."""

    if not description:
        return None
    for pattern in (_REQUIRED_BEFORE, _REQUIRED_AFTER):
        for match in pattern.finditer(description):
            language = next(group for group in match.groups() if group and group.casefold() in LANGUAGES)
            window = description[max(0, match.start() - 60) : match.end() + 60]
            if _OPTIONAL.search(window):
                continue
            return language.casefold()
    return None


def written_language(description: str | None) -> str | None:
    """The foreign language the posting is written in, or None when English, Spanish or unclear."""

    if not description:
        return None
    words = [word.casefold() for word in _WORD.findall(description)]
    if len(words) < MIN_WORDS:
        return None
    scores = {
        language: sum(1 for word in words if word in vocabulary) / len(words)
        for language, vocabulary in _FUNCTION_WORDS.items()
    }
    best = max(scores, key=lambda language: scores[language])
    if best == "english" or scores[best] < 0.12 or scores[best] < 1.6 * scores["english"]:
        return None
    return best
