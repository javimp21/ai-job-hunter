"""Build ATS adapters from validated local source configuration."""

from __future__ import annotations

from collections.abc import Collection, Mapping

import httpx

from ai_job_hunter.connectors.amazon_jobs import AmazonJobsConnector
from ai_job_hunter.connectors.careers_site import CareersSiteConnector, job_url_title
from ai_job_hunter.connectors.ashby import AshbyConnector
from ai_job_hunter.connectors.greenhouse import GreenhouseConnector
from ai_job_hunter.connectors.lever import LeverConnector
from ai_job_hunter.connectors.protocol import JobConnector
from ai_job_hunter.candidates.prefilter import title_may_be_relevant
from ai_job_hunter.connectors.smartrecruiters import SmartRecruitersConnector
from ai_job_hunter.connectors.recruitee import RecruiteeConnector
from ai_job_hunter.connectors.teamtailor import TeamtailorConnector
from ai_job_hunter.connectors.factorial import FactorialConnector
from ai_job_hunter.connectors.personio import PersonioConnector
from ai_job_hunter.connectors.workable import WorkableConnector
from ai_job_hunter.connectors.workday import WorkdayConnector
from ai_job_hunter.job_sources import JobSourcesConfig


def build_job_connectors(
    config: JobSourcesConfig,
    *,
    client: httpx.Client | None = None,
    timeout: float = 20.0,
    known_urls: Mapping[str, Collection[str]] | None = None,
) -> list[JobConnector]:
    """Create one provider connector per configured company without hardcoding names.

    ``known_urls`` maps a careers-site identifier (lower-case) to the job page URLs the
    caller already stores, so those pages are not fetched again.
    """

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
        elif source.provider == "ashby":
            connectors.append(
                AshbyConnector(
                    source.identifier,
                    company_name=source.company_name,
                    max_jobs=source.max_jobs,
                    timeout=timeout,
                    client=client,
                )
            )
        elif source.provider == "teamtailor":
            connectors.append(
                TeamtailorConnector(
                    source.identifier,
                    company_name=source.company_name,
                    max_jobs=source.max_jobs,
                    timeout=timeout,
                    client=client,
                )
            )
        elif source.provider == "recruitee":
            connectors.append(
                RecruiteeConnector(
                    source.identifier,
                    company_name=source.company_name,
                    max_jobs=source.max_jobs,
                    timeout=timeout,
                    client=client,
                )
            )
        elif source.provider == "smartrecruiters":
            connectors.append(
                SmartRecruitersConnector(
                    source.identifier,
                    company_name=source.company_name,
                    max_jobs=source.max_jobs,
                    timeout=timeout,
                    client=client,
                    # One detail request per posting: skip clearly non-target titles.
                    detail_filter=title_may_be_relevant,
                )
            )
        elif source.provider == "workable":
            connectors.append(
                WorkableConnector(
                    source.identifier,
                    company_name=source.company_name,
                    max_jobs=source.max_jobs,
                    timeout=timeout,
                    client=client,
                )
            )
        elif source.provider == "personio":
            connectors.append(
                PersonioConnector(
                    source.identifier,
                    company_name=source.company_name,
                    region=source.region or "de",
                    max_jobs=source.max_jobs,
                    timeout=timeout,
                    client=client,
                )
            )
        elif source.provider == "factorial":
            connectors.append(
                FactorialConnector(
                    source.identifier,
                    company_name=source.company_name,
                    region=source.region or "com",
                    max_jobs=source.max_jobs,
                    timeout=timeout,
                    client=client,
                    # One detail request per posting: skip clearly non-target titles.
                    detail_filter=title_may_be_relevant,
                )
            )
        elif source.provider == "workday":
            assert source.region is not None  # enforced by JobSourceSpec
            connectors.append(
                WorkdayConnector(
                    source.identifier,
                    company_name=source.company_name,
                    region=source.region,
                    max_jobs=source.max_jobs,
                    timeout=timeout,
                    client=client,
                    # One detail request per posting: skip clearly non-target titles.
                    detail_filter=title_may_be_relevant,
                )
            )
        elif source.provider == "careers_site":
            connectors.append(
                CareersSiteConnector(
                    source.identifier,
                    company_name=source.company_name,
                    max_jobs=source.max_jobs,
                    timeout=timeout,
                    client=client,
                    known_urls=(known_urls or {}).get(source.identifier.casefold(), ()),
                    # One detail request per job page: skip URLs whose slug names a non-target role.
                    url_filter=lambda url: title_may_be_relevant(job_url_title(url) or "engineer"),
                )
            )
        elif source.provider == "amazon_jobs":
            connectors.append(
                AmazonJobsConnector(
                    source.identifier,
                    company_name=source.company_name,
                    max_jobs=source.max_jobs,
                    timeout=timeout,
                    client=client,
                )
            )
        else:  # Defensive: the config model already restricts this to supported providers.
            raise ValueError(f"Unsupported job source provider: {source.provider}")
    return connectors
