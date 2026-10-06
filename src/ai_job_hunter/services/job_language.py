"""Spoken-language requirements of a posting, relative to the languages the candidate speaks.

Two soft signals, never a rejection (they only lower the review priority):

* the posting asks for another language as a requirement ("fluent German", "Dutch required"), unless
  the wording marks it as optional ("German is a plus") or the candidate speaks that language;
* the posting itself is written in another language (German, Dutch, French, a Nordic language), which
  almost always means the team works in it.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

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
    "spanish": {"el", "la", "los", "las", "de", "del", "en", "y", "que", "con", "para", "por", "una", "un", "se", "su",
                "sus", "es", "al", "como", "más", "no", "experiencia", "trabajo", "equipo", "empresa", "desarrollo"},
    "portuguese": {"não", "você", "vocês", "uma", "são", "também", "nós", "seu", "sua", "está", "ao", "aos", "às", "dos",
                   "das", "pelo", "pela", "empresa", "vaga", "trabalho", "experiência", "conhecimento", "desenvolvimento",
                   "equipa", "equipe", "e", "o", "os", "em", "na", "no", "com"},
    "italian": {"il", "lo", "gli", "della", "delle", "per", "con", "una", "che", "sono", "nel", "nella", "dei", "degli",
                "anche", "non", "più", "lavoro", "azienda", "esperienza", "squadra", "e", "di", "la", "le"},
    "polish": {"i", "w", "na", "z", "do", "się", "jest", "dla", "oraz", "nie", "jako", "pracy", "firma", "doświadczenie",
               "zespół", "będziesz", "naszym", "lub"},
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


_ALIASES = {
    "aleman": "german", "deutsch": "german", "german": "german",
    "neerlandes": "dutch", "holandes": "dutch", "nederlands": "dutch", "dutch": "dutch",
    "frances": "french", "francais": "french", "french": "french",
    "sueco": "swedish", "svenska": "swedish", "swedish": "swedish",
    "danes": "danish", "dansk": "danish", "danish": "danish",
    "noruego": "norwegian", "norsk": "norwegian", "norwegian": "norwegian",
    "finlandes": "finnish", "suomi": "finnish", "finnish": "finnish",
    "italiano": "italian", "italian": "italian",
    "portugues": "portuguese", "portuguese": "portuguese",
}


def spoken_languages(entries: Iterable[str]) -> frozenset[str]:
    """Languages from a profile list such as ``["Spanish (native)", "alemán B1"]`` that postings may ask for."""

    found: set[str] = set()
    for entry in entries:
        folded = "".join(
            ch for ch in unicodedata.normalize("NFKD", entry.casefold()) if not unicodedata.combining(ch)
        )
        for word in re.findall(r"[a-z]+", folded):
            if word in _ALIASES:
                found.add(_ALIASES[word])
    return frozenset(found)


def required_foreign_language(description: str | None, *, spoken: frozenset[str] = frozenset()) -> str | None:
    """A spoken language the posting requires (not marked optional) and the candidate lacks, or None."""

    if not description:
        return None
    for pattern in (_REQUIRED_BEFORE, _REQUIRED_AFTER):
        for match in pattern.finditer(description):
            language = next(group for group in match.groups() if group and group.casefold() in LANGUAGES)
            if language.casefold() in spoken:
                continue
            window = description[max(0, match.start() - 60) : match.end() + 60]
            if _OPTIONAL.search(window):
                continue
            return language.casefold()
    return None


def written_language(description: str | None, *, spoken: frozenset[str] = frozenset()) -> str | None:
    """The foreign language the posting is written in, or None when English, Spanish, spoken or unclear."""

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
    home = max(scores["english"], scores["spanish"])
    if best in {"english", "spanish"} or best in spoken or scores[best] < 0.12 or scores[best] < 1.6 * home:
        return None
    return best
