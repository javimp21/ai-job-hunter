"""Build ATS adapters from validated local source configuration."""

from __future__ import annotations

import httpx

from ai_job_hunter.connectors.greenhouse import GreenhouseConnector
from ai_job_hunter.connectors.lever import LeverConnector
from ai_job_hunter.connectors.protocol import JobConnector
from ai_job_hunter.job_sources import JobSourcesConfig


def build_job_connectors(
    config: JobSourcesConfig,
    *,
    client: httpx.Client | None = None,
    timeout: float = 20.0,
) -> list[JobConnector]:
    """Create one provider connector per configured company without hardcoding names."""

    connectors: list[JobConnector] = []
    for source in config.sources:
        if source.provider == "greenhouse":
            connectors.append(
                GreenhouseConnector(
                    source.identifier,
                    company_name=source.company_name,
                    max_jobs=source.max_jobs,
                    timeout=timeout,
                    client=client,
                )
            )
        elif source.provider == "lever":
            connectors.append(
                LeverConnector(
                    source.identifier,
                    company_name=source.company_name,
                    region=source.region or "global",
                    max_jobs=source.max_jobs,
                    timeout=timeout,
                    client=client,
                )
            )
        else:  # Defensive: the config model already restricts this to supported providers.
            raise ValueError(f"Unsupported job source provider: {source.provider}")
    return connectors
