"""Shared read-only JSON GET for job-portal connectors."""

from __future__ import annotations

from typing import Any

import httpx

USER_AGENT = "AI-Job-Hunter/0.1 (personal job discovery)"


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
