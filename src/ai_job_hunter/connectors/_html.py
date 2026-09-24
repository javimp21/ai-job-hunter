"""Small HTML-to-text helper for job-board descriptions."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser


class _ReadableTextParser(HTMLParser):
    _BLOCK_TAGS = {
        "address", "article", "blockquote", "br", "dd", "div", "dl", "dt",
        "h1", "h2", "h3", "h4", "h5", "h6", "hr", "li", "ol", "p",
        "pre", "section", "table", "tr", "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipped_tags: list[str] = []

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.skipped_tags.append(tag)
        elif not self.skipped_tags and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            if tag in self.skipped_tags:
                self.skipped_tags.remove(tag)
        elif not self.skipped_tags and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skipped_tags:
            self.parts.append(data)


def html_to_text(value: str | None) -> str | None:
    """Decode HTML once and retain readable paragraph/list boundaries."""

    if not value:
        return None
    parser = _ReadableTextParser()
    parser.feed(html.unescape(value))
    parser.close()
    text = "".join(parser.parts).replace("\xa0", " ")
    lines = [re.sub(r"[\t\r\f\v ]+", " ", line).strip() for line in text.splitlines()]
    result = "\n".join(line for line in lines if line)
    return result or None
