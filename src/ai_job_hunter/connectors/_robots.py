"""Minimal robots.txt rules for polite, read-only connectors.

``urllib.robotparser`` ignores the ``*`` and ``$`` wildcards that most careers sites
use (``Disallow: */apply``), so this module implements the longest-match rules of
RFC 9309: the group naming our product token wins over ``*``; the longest matching
pattern decides; ``Allow`` wins a tie; no matching rule means allowed.
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

_MAX_RULES = 2000


class RobotsRules:
    """Parsed rules for one user agent plus the file's ``Sitemap`` lines and crawl delay."""

    def __init__(self, text: str | None, user_agent_token: str) -> None:
        self.sitemaps: list[str] = []
        self.crawl_delay: float | None = None
        self._rules: list[tuple[int, bool, re.Pattern[str]]] = []
        if text is not None:
            self._parse(text, user_agent_token.casefold())

    def _parse(self, text: str, token: str) -> None:
        groups: list[tuple[list[str], list[tuple[bool, str]], float | None]] = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        delay: float | None = None
        in_rules = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            name, separator, value = line.partition(":")
            if not separator:
                continue
            name, value = name.strip().casefold(), value.strip()
            if name == "sitemap":
                if value:
                    self.sitemaps.append(value)
            elif name == "user-agent":
                if in_rules:
                    groups.append((agents, rules, delay))
                    agents, rules, delay, in_rules = [], [], None, False
                agents.append(value.casefold())
            elif name in {"allow", "disallow"}:
                in_rules = True
                if value and len(rules) < _MAX_RULES:
                    rules.append((name == "allow", value))
            elif name == "crawl-delay":
                in_rules = True
                try:
                    delay = float(value)
                except ValueError:
                    pass
        if agents:
            groups.append((agents, rules, delay))
        specific = [group for group in groups if any(agent and agent != "*" and agent in token for agent in group[0])]
        chosen = specific or [group for group in groups if "*" in group[0]]
        for _agents, group_rules, group_delay in chosen:
            if group_delay is not None:
                self.crawl_delay = group_delay
            for allow, pattern in group_rules:
                self._rules.append((len(pattern), allow, _compile(pattern)))

    def can_fetch(self, url: str) -> bool:
        parts = urlsplit(url)
        path = unquote(parts.path or "/") + (f"?{unquote(parts.query)}" if parts.query else "")
        best: tuple[int, bool] | None = None
        for length, allow, pattern in self._rules:
            if pattern.match(path) and (best is None or length > best[0] or (length == best[0] and allow)):
                best = (length, allow)
        return True if best is None else best[1]


def _compile(pattern: str) -> re.Pattern[str]:
    pattern = unquote(pattern)
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    expression = ".*".join(re.escape(piece) for piece in body.split("*"))
    return re.compile(expression + ("$" if anchored else ""))
