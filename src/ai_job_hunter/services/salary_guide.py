"""Rough junior salary expectations by country, for postings that publish no salary.

The figures are the candidate's own estimates (gross per year, about one year of experience,
backend/software roles) kept in code so every alert can suggest what to answer when a form asks
for expectations. They are orientation, not facts about any employer: revisit them now and then.
"""

from __future__ import annotations

import re
import unicodedata

from ai_job_hunter.candidates.prefilter import countries_in_text

# country: (low, answer, high, currency)
SALARY_GUIDE: dict[str, tuple[int, int, int, str]] = {
    "Spain": (28_000, 32_000, 34_000, "€"),
    "Netherlands": (40_000, 46_000, 50_000, "€"),
    "Ireland": (38_000, 44_000, 48_000, "€"),
    "Luxembourg": (45_000, 52_000, 58_000, "€"),
    "Switzerland": (70_000, 80_000, 90_000, "CHF"),
}


def _amount(value: int, currency: str) -> str:
    text = f"{value:,}".replace(",", ".")
    return f"{text} {currency}"


# Places the country detector may not know: cities, regions and cantons of the guided countries.
_PLACES = {
    "Spain": ("madrid", "barcelona", "valencia", "sevilla", "seville", "bilbao", "malaga", "zaragoza", "catalonia",
              "catalunya", "andalucia", "alcobendas", "alcorcon", "pozuelo", "las rozas", "getafe", "leganes"),
    "Netherlands": ("amsterdam", "rotterdam", "the hague", "den haag", "utrecht", "eindhoven", "groningen", "assen",
                    "rijswijk", "delft", "leiden", "breda", "tilburg", "north holland", "south holland", "drenthe",
                    "noord-brabant", "gelderland", "overijssel", "zeeland", "flevoland", "friesland", "limburg"),
    "Ireland": ("dublin", "cork", "galway", "limerick", "waterford", "leinster", "munster", "connacht"),
    "Luxembourg": ("luxembourg", "luxemburgo", "esch-sur-alzette", "kirchberg"),
    "Switzerland": ("zurich", "zuerich", "geneva", "geneve", "basel", "bern", "berne", "lausanne", "zug", "lugano",
                    "bioggio", "ticino", "vaud", "winterthur", "lucerne", "st. gallen", "baden"),
}
_PLACE_PATTERNS = {
    country: re.compile(r"(?<![a-z])(?:" + "|".join(re.escape(place) for place in places) + r")(?![a-z])")
    for country, places in _PLACES.items()
}


def _fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(ch))


def expectation_hint(location: str | None) -> str | None:
    """Suggested answer for the job's single guided country, or None when it is unclear or mixed."""

    if not location:
        return None
    folded = _fold(location)
    countries = set(countries_in_text(location))
    countries.update(country for country, pattern in _PLACE_PATTERNS.items() if pattern.search(folded))
    if len(countries) != 1 or next(iter(countries)) not in SALARY_GUIDE:
        return None
    low, answer, high, currency = SALARY_GUIDE[next(iter(countries))]
    return f"{_amount(answer, currency)} (rango {_amount(low, currency)} a {_amount(high, currency)})"
