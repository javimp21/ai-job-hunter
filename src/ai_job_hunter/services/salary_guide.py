"""Suggested salary expectation by country, for postings that publish no salary.

The figures live in the candidate's own configuration (``tuning.salary_guide``: country ->
low/answer/high/currency, gross per year) so every alert can suggest what to answer when a form asks
for expectations. They are orientation, not facts about any employer: revisit them now and then.
Without a guide, or for a country it does not list, no hint is shown.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping

from ai_job_hunter.candidates.prefilter import countries_in_text
from ai_job_hunter.candidates.profile import SalaryGuideEntry


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
    "Germany": ("berlin", "munich", "munchen", "hamburg", "frankfurt", "cologne", "koln", "stuttgart", "dusseldorf",
                "leipzig", "dresden", "nuremberg", "nurnberg", "hannover", "bremen", "karlsruhe", "bavaria", "bayern"),
    "Belgium": ("brussels", "bruxelles", "brussel", "antwerp", "antwerpen", "ghent", "gent", "leuven", "liege",
                "flanders", "wallonia"),
    "Sweden": ("stockholm", "gothenburg", "goteborg", "malmo", "uppsala", "linkoping", "lund", "vasteras"),
    "Denmark": ("copenhagen", "kobenhavn", "aarhus", "odense", "aalborg"),
    "Finland": ("helsinki", "espoo", "tampere", "oulu", "turku", "vantaa"),
    "Norway": ("oslo", "bergen", "trondheim", "stavanger", "tromso"),
    "Switzerland": ("zurich", "zuerich", "geneva", "geneve", "basel", "bern", "berne", "lausanne", "zug", "lugano",
                    "bioggio", "ticino", "vaud", "winterthur", "lucerne", "st. gallen", "baden"),
}
_PLACE_PATTERNS = {
    country: re.compile(r"(?<![a-z])(?:" + "|".join(re.escape(place) for place in places) + r")(?![a-z])")
    for country, places in _PLACES.items()
}


def _fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(ch))


def expectation_hint(location: str | None, guide: Mapping[str, SalaryGuideEntry]) -> str | None:
    """Suggested answer for the job's single guided country, or None when it is unclear or mixed."""

    if not location or not guide:
        return None
    folded = _fold(location)
    countries = set(countries_in_text(location))
    countries.update(country for country, pattern in _PLACE_PATTERNS.items() if pattern.search(folded))
    if len(countries) != 1 or next(iter(countries)) not in guide:
        return None
    entry = guide[next(iter(countries))]
    low, answer, high, currency = entry.low, entry.answer, entry.high, entry.currency
    return f"{_amount(answer, currency)} (rango {_amount(low, currency)} a {_amount(high, currency)})"
