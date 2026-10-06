"""Work mode and salary stated in the free text of a posting (English and Spanish), for display only.

Source feeds often leave the work mode and the salary empty although the description says them
("modelo híbrido", "fully remote", "25.000 - 35.000 € brutos"). Alerts show what the text says, marked as
read from the text. These values are hints: they never feed the evaluation, the priority or any filter, so
an uncertain reading can only cost a wrong label, never a wrong decision.

Only explicit wording counts. A posting that mentions two different work modes, or only a loose use of the
word ("remote teams"), yields nothing.
"""

from __future__ import annotations

import re

_REMOTE = re.compile(
    r"\b(?:100\s?%|fully|full|completely|totally)[ -]?remote\b|\bremote[- ]first\b|\bremote\s*\(\s*(?:spain|europe|emea|eu)\b"
    r"|\b100\s?%\s*(?:remoto|teletrabajo)\b|\bteletrabajo\s*(?:100\s?%|\btotal\b)|\btotalmente\s+remot[oa]\b"
    r"|\b100\s?%\s*en\s*remoto\b|\bfully\s+distributed\b|\bwork\s+from\s+anywhere\b",
    re.IGNORECASE,
)
_HYBRID = re.compile(
    r"\bhybrid\b|\bh[ií]brid[oa]\b|\bhybride\b|\b\d\s*(?:-|–|to|a)?\s*\d?\s*days?\s+(?:per\s+week\s+)?(?:in|at)\s+(?:the\s+)?office\b"
    r"|\b\d\s*(?:-|–|a)?\s*\d?\s*d[ií]as?\s+(?:a\s+la\s+semana\s+)?(?:en|de)\s+(?:la\s+)?oficina\b",
    re.IGNORECASE,
)
_ONSITE = re.compile(
    r"(?<!not\s)(?<!no\s)\bon[- ]?site\b|\bpresencial\b|\bin[- ]office\s+(?:role|position|only)\b|\b5\s+days\s+(?:in|at)\s+(?:the\s+)?office\b",
    re.IGNORECASE,
)

_AMOUNT = r"\d{1,3}(?:[.,\s'’]\d{3})+|\d{2,3}\s?[kK]\b|\d{4,6}"
_MONEY = rf"(?:{_AMOUNT})"
_CURRENCY = r"(?:€|EUR|eur|euros?|\$|USD|usd|CHF|chf|£|GBP|gbp)"
_SALARY_RANGE = re.compile(
    rf"(?P<c1>{_CURRENCY})?\s?(?P<low>{_MONEY})\s?(?P<c2>{_CURRENCY})?\s?(?:-|–|—|to|a|hasta)\s?(?P<c3>{_CURRENCY})?\s?(?P<high>{_MONEY})\s?(?P<c4>{_CURRENCY})?"
    r"(?P<period>\s?(?:/|per\s+|al\s+|brutos?\s+(?:al\s+)?)?\s?(?:year|yr|a[nñ]o|annum|month|mes)\b)?",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\d+")


def work_mode_from_text(*parts: str | None) -> str | None:
    """REMOTE, HYBRID or ONSITE when the text states exactly one of them explicitly, else None."""

    text = " ".join(part for part in parts if part)[:20000]
    if not text:
        return None
    found = {
        mode
        for mode, pattern in (("REMOTE", _REMOTE), ("HYBRID", _HYBRID), ("ONSITE", _ONSITE))
        if pattern.search(text)
    }
    return next(iter(found)) if len(found) == 1 else None


def _to_number(raw: str) -> int | None:
    raw = raw.strip()
    if raw[-1:] in {"k", "K"}:
        digits = _NUMBER.findall(raw[:-1])
        return int("".join(digits)) * 1000 if digits else None
    digits = "".join(_NUMBER.findall(raw))
    return int(digits) if digits else None


def salary_from_text(description: str | None) -> str | None:
    """A yearly salary range written in the text ("25.000 - 35.000 €"), as short display text, or None.

    Requires a currency next to the figures and amounts of a plausible yearly salary (10,000 to 600,000), so
    funding rounds, revenues and phone numbers are not read as pay.
    """

    if not description:
        return None
    for match in _SALARY_RANGE.finditer(description[:20000]):
        currency = next((match.group(name) for name in ("c1", "c2", "c3", "c4") if match.group(name)), None)
        low, high = _to_number(match.group("low")), _to_number(match.group("high"))
        if currency is None or low is None or high is None or not 10_000 <= low <= high <= 600_000:
            continue
        period = (match.group("period") or "").casefold()
        if "mes" in period or "month" in period:
            continue  # monthly figures are not comparable with the yearly guide; keep the display simple
        symbol = {"eur": "€", "euro": "€", "euros": "€", "usd": "$", "gbp": "£", "chf": "CHF"}.get(currency.casefold(), currency)
        return f"{low:,}".replace(",", ".") + "–" + f"{high:,}".replace(",", ".") + f" {symbol}"
    return None
