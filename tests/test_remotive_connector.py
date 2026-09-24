import json
from datetime import UTC
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from ai_job_hunter.connectors import JobConnector, RemotiveConnector, RemotiveConnectorError
from ai_job_hunter.domain.normalized_job import (
    EmploymentType,
    RemoteEligibility,
    RemotePolicy,
    SalaryPeriod,
)
from ai_job_hunter.models import Company, Job, JobSource
from ai_job_hunter.services.pipeline import run_ingestion_pipeline

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "remotive_response.json"


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def mocked_connector(
    response: httpx.Response | None = None,
    *,
    payload: Any = None,
    status_code: int = 200,
    handler: Any = None,
    **connector_args: Any,
) -> tuple[RemotiveConnector, httpx.Client]:
    if handler is None:
        body = payload if payload is not None else load_fixture()
        handler = lambda request: response or httpx.Response(status_code, json=body)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return RemotiveConnector(client=client, **connector_args), client


def test_remotive_connector_normalizes_multiple_offers_and_preserves_source_payload() -> None:
    connector, client = mocked_connector(limit=2)
    try:
        assert isinstance(connector, JobConnector)
        first, second = connector.fetch_jobs()
    finally:
        client.close()

    assert first.provider == "remotive"
    assert first.external_id == "101"
    assert first.source_url == "https://remotive.com/remote-jobs/product/lead-backend-engineer-101"
    assert first.canonical_url is None
    assert first.apply_url is None
    assert first.title == "Lead Backend Engineer"
    assert first.company_name == "Acme Labs"
    assert first.company_website is None  # A logo URL is not a company website.
    assert first.description == "Build reliable services.\nOwn APIs\nWork with teams & customers"
    assert first.raw_metadata["description"].startswith("<p>")
    assert first.remote_policy is RemotePolicy.REMOTE
    assert first.remote_eligibility is RemoteEligibility.SPAIN_ONLY
    assert first.salary_min == Decimal("50000")
    assert first.salary_max == Decimal("70000")
    assert first.currency == "EUR"
    assert first.salary_period is SalaryPeriod.YEAR
    assert first.employment_type is EmploymentType.FULL_TIME
    assert first.published_at is not None and first.published_at.tzinfo is UTC
    assert first.discovered_at.tzinfo is UTC

    assert second.external_id == "202"
    assert second.company_name == "ACME LABS"
    assert second.description is None
    assert second.salary_min is None
    assert second.salary_max is None
    assert second.currency is None
    assert second.salary_period is None
    assert second.employment_type is EmploymentType.PART_TIME
    assert second.location == "Worldwide"
    assert second.remote_eligibility is RemoteEligibility.WORLDWIDE
    assert second.published_at is None  # The source timestamp has no timezone.
    assert second.raw_metadata["publication_date"] == "2026-09-21T12:00:00"


def test_remotive_connector_accepts_missing_optional_fields() -> None:
    connector, client = mocked_connector(
        payload={
            "jobs": [
                {
                    "url": "https://remotive.com/remote-jobs/engineering/role-303",
                    "title": "Platform Engineer",
                }
            ]
        }
    )
    try:
        (offer,) = connector.fetch_jobs()
    finally:
        client.close()

    assert offer.external_id is None
    assert offer.company_name is None
    assert offer.company_website is None
    assert offer.description is None
    assert offer.location is None
    assert offer.remote_policy is RemotePolicy.REMOTE
    assert offer.remote_eligibility is RemoteEligibility.UNKNOWN
    assert offer.salary_min is None
    assert offer.currency is None
    assert offer.employment_type is None
    assert offer.published_at is None


def test_remotive_connector_passes_documented_filters_and_identifying_headers() -> None:
    requests: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"jobs": []})

    connector, client = mocked_connector(
        handler=capture,
        limit=7,
        search="backend engineer",
        category="software-dev",
        company_name="Acme",
    )
    try:
        assert connector.fetch_jobs() == []
    finally:
        client.close()

    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == (
        "https://remotive.com/api/remote-jobs?search=backend+engineer"
        "&category=software-dev&company_name=Acme&limit=7"
    )
    assert request.headers["user-agent"].startswith("AI-Job-Hunter/")
    assert request.headers["accept"] == "application/json"


def test_remotive_connector_caps_results_if_api_overdelivers_limit() -> None:
    connector, client = mocked_connector(limit=1)
    try:
        offers = connector.fetch_jobs()
    finally:
        client.close()

    assert len(offers) == 1
    assert offers[0].external_id == "101"


def test_remotive_connector_reports_http_error_without_response_body() -> None:
    connector, client = mocked_connector(
        payload={"error": "private response body"}, status_code=503
    )
    try:
        with pytest.raises(RemotiveConnectorError, match="HTTP 503") as error:
            connector.fetch_jobs()
    finally:
        client.close()

    assert "private response body" not in str(error.value)


def test_remotive_connector_reports_invalid_json() -> None:
    connector, client = mocked_connector(
        handler=lambda request: httpx.Response(200, content=b"not-json")
    )
    try:
        with pytest.raises(RemotiveConnectorError, match="invalid JSON"):
            connector.fetch_jobs()
    finally:
        client.close()


@pytest.mark.parametrize("payload", [[], {}, {"jobs": "not-a-list"}, {"jobs": [None]}])
def test_remotive_connector_rejects_malformed_response_shapes(payload: Any) -> None:
    connector, client = mocked_connector(payload=payload)
    try:
        with pytest.raises(RemotiveConnectorError):
            connector.fetch_jobs()
    finally:
        client.close()


def test_remotive_connector_keeps_ambiguous_salary_unstructured() -> None:
    connector, client = mocked_connector(
        payload={
            "jobs": [
                {
                    "id": 404,
                    "url": "https://remotive.com/remote-jobs/engineering/role-404",
                    "title": "Engineer",
                    "salary": "$40,000 - $50,000",
                }
            ]
        }
    )
    try:
        (offer,) = connector.fetch_jobs()
    finally:
        client.close()

    assert offer.salary_min is None
    assert offer.salary_max is None
    assert offer.currency is None
    assert offer.raw_metadata["salary"] == "$40,000 - $50,000"


def test_remotive_connector_integrates_with_pipeline_and_exact_idempotency(db_session) -> None:
    connector, client = mocked_connector(limit=2)
    try:
        first = run_ingestion_pipeline(connector, db_session)
        second = run_ingestion_pipeline(connector, db_session)
    finally:
        client.close()

    assert (first.fetched, first.created, first.already_known, first.failed) == (2, 2, 0, 0)
    assert (second.fetched, second.created, second.already_known, second.failed) == (2, 0, 2, 0)
    assert db_session.scalar(select(func.count()).select_from(Company)) == 1
    assert db_session.scalar(select(func.count()).select_from(Job)) == 2
    assert db_session.scalar(select(func.count()).select_from(JobSource)) == 2
    assert db_session.scalar(select(JobSource.provider).limit(1)) == "remotive"
    assert db_session.scalar(select(JobSource.original_url).limit(1)).startswith(
        "https://remotive.com/remote-jobs/"
    )
