"""Typographic hygiene for drafted letters: plain punctuation and no invisible characters.

Generated text tends to carry em dashes, curly quotes and, now and then, zero-width or other
format characters that survive copy-paste. A person typing a letter produces none of them, so the
drafts are normalised before they are saved. Wording is never changed; letters stay as written.
"""

from __future__ import annotations

import re
import unicodedata

_SPACES = {" ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " "}
_QUOTES = {"‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"', "„": '"'}
_EM_DASH = re.compile(r"\s*—\s*")
_SPACED_EN_DASH = re.compile(r"\s+–\s+")


def clean_letter_text(text: str) -> str:
    for source, target in _SPACES.items():
        text = text.replace(source, target)
    # Format characters (zero-width spaces and joiners, word joiner, soft hyphen, BOM, tags).
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    for source, target in _QUOTES.items():
        text = text.replace(source, target)
    text = _EM_DASH.sub(", ", text)
    text = _SPACED_EN_DASH.sub(", ", text).replace("–", "-")
    text = text.replace("…", "...")
    text = re.sub(r",\s*([,.;:!?])", r"\1", text)
    return re.sub(r"[ \t]+\n", "\n", text)
