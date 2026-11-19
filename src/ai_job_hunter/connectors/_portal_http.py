"""Shared read-only HTTP helpers for job-portal connectors."""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from typing import Any

import httpx

USER_AGENT = "AI-Job-Hunter/0.1 (personal job discovery)"
_MAX_FEED_BYTES = 4_000_000
_INVALID_XML_CONTROLS = bytes(value for value in range(32) if value not in (9, 10, 13))


def new_client(timeout: float) -> httpx.Client:
    return httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})


def get_json(
    client: httpx.Client,
    url: str,
    params: dict[str, Any] | None,
    *,
    portal: str,
    error: type[Exception],
    timeout: float,
) -> Any:
    """GET ``url`` and decode JSON, raising only safe messages (status or type, never the URL or params)."""

    try:
        response = client.get(url, params=params, timeout=timeout)
    except httpx.HTTPError as exc:
        raise error(f"{portal} request failed ({type(exc).__name__}).") from None
    if response.status_code != 200:
        raise error(f"{portal} returned HTTP {response.status_code}.")
    try:
        return response.json()
    except ValueError:
        raise error(f"{portal} returned invalid JSON.") from None


def get_rss(
    client: httpx.Client, url: str, *, portal: str, error: type[Exception], timeout: float
) -> ElementTree.Element:
    root = get_xml(client, url, portal=portal, error=error, timeout=timeout)
    if root.tag != "rss" or root.find("channel") is None:
        raise error(f"{portal} feed is not an RSS document.")
    return root


def get_xml(
    client: httpx.Client,
    url: str,
    *,
    portal: str,
    error: type[Exception],
    timeout: float,
    params: dict[str, Any] | None = None,
    strip_utf8_controls: bool = False,
) -> ElementTree.Element:
    content = bytearray()
    try:
        with client.stream("GET", url, params=params, timeout=timeout, follow_redirects=False) as response:
            if response.status_code != 200:
                raise error(f"{portal} returned HTTP {response.status_code}.")
            for chunk in response.iter_bytes():
                if len(content) + len(chunk) > _MAX_FEED_BYTES:
                    raise error(f"{portal} feed is too large.")
                content.extend(chunk)
    except httpx.HTTPError as exc:
        raise error(f"{portal} request failed ({type(exc).__name__}).") from None

    if strip_utf8_controls:
        # Some UTF-8 feeds put invalid XML control characters in imported job descriptions.
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            raise error(f"{portal} feed is not valid UTF-8.") from None
        content = content.translate(None, _INVALID_XML_CONTROLS)
    # ElementTree expands internal entities. Strip UTF-16/32 nulls when checking for a DTD.
    probe = content.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in probe or b"<!ENTITY" in probe:
        raise error(f"{portal} feed contains a forbidden DTD declaration.")
    try:
        return ElementTree.fromstring(content)
    except (ElementTree.ParseError, LookupError, ValueError):
        raise error(f"{portal} feed is not valid XML.") from None


def post_json(
    client: httpx.Client,
    url: str,
    body: dict[str, Any],
    *,
    headers: dict[str, str],
    portal: str,
    error: type[Exception],
    timeout: float,
) -> Any:
    """POST a JSON ``body`` and decode the JSON answer, raising only safe messages (never the URL, body or headers)."""

    try:
        response = client.post(url, json=body, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        raise error(f"{portal} request failed ({type(exc).__name__}).") from None
    if response.status_code != 200:
        raise error(f"{portal} returned HTTP {response.status_code}.")
    try:
        return response.json()
    except ValueError:
        raise error(f"{portal} returned invalid JSON.") from None
