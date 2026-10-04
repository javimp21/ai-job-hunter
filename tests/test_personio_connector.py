from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from ai_job_hunter.connectors import JobConnector, PersonioConnector, PersonioConnectorError
from ai_job_hunter.domain.normalized_job import EmploymentType, RemoteEligibility

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<workzag-jobs>
<position>
    <id>111</id>
    <subcompany>Example GmbH</subcompany>
    <office>Barcelona</office>
    <additionalOffices><office>Madrid</office><office>Barcelona</office></additionalOffices>
    <department>Engineering</department>
    <recruitingCategory>Permanent Employee</recruitingCategory>
    <name>Backend Engineer</name>
    <jobDescriptions>
        <jobDescription>
            <name>Your Mission</name>
            <value><![CDATA[<p>Build <strong>APIs</strong>.</p><ul><li>Python</li></ul>]]></value>
        </jobDescription>
        <jobDescription>
            <name>Empty</name>
            <value></value>
        </jobDescription>
    </jobDescriptions>
    <employmentType>permanent</employmentType>
    <seniority>experienced</seniority>
    <schedule>full-time</schedule>
    <yearsOfExperience>1-2</yearsOfExperience>
    <createdAt>2026-06-05T16:21:06+00:00</createdAt>
</position>
<position>
    <id>222</id>
    <office></office>
    <name>Designer</name>
    <schedule>full-or-part-time</schedule>
    <createdAt>garbage</createdAt>
</position>
</workzag-jobs>
"""


def make_connector(*, body: bytes | None = None, status=200, handler=None, **kwargs):
    if handler is None:
        handler = lambda _request: httpx.Response(status, content=body if body is not None else FEED.encode())
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return PersonioConnector("example", client=client, **kwargs), client


def test_connector_reads_xml_feed_and_normalizes_positions():
    requests = []
    connector, client = make_connector(
        handler=lambda req: (requests.append(req), httpx.Response(200, content=FEED.encode()))[1],
        company_name="Example Co",
    )
    try:
        assert isinstance(connector, JobConnector)
        first, second = connector.fetch_jobs()
    finally:
        client.close()

    assert [str(r.url) for r in requests] == ["https://example.jobs.personio.de/xml"]
    assert first.provider == "personio"
    assert first.external_id == "111"
    assert first.title == "Backend Engineer"
    assert first.company_name == "Example Co"
    assert first.source_url == first.apply_url == "https://example.jobs.personio.de/job/111"
    assert first.description == "Your Mission\nBuild APIs.\nPython"
    assert first.location == "Barcelona; Madrid"
    assert first.remote_policy is None
    assert first.remote_eligibility is RemoteEligibility.UNKNOWN
    assert first.employment_type is EmploymentType.FULL_TIME
    assert first.published_at == datetime(2026, 6, 5, 16, 21, 6, tzinfo=UTC)
    assert first.raw_metadata["subcompany"] == "Example GmbH"

    assert first.company_name == "Example Co"  # the legal entity ("subcompany") is never used as name
    assert second.raw_metadata["subcompany"] is None
    assert second.location is None
    assert second.description is None
    assert second.employment_type is None
    assert second.published_at is None


def test_com_region_and_max_jobs():
    requests = []
    connector, client = make_connector(
        handler=lambda req: (requests.append(req), httpx.Response(200, content=FEED.encode()))[1],
        region="com",
        max_jobs=1,
    )
    try:
        assert len(connector.fetch_jobs()) == 1
    finally:
        client.close()
    assert str(requests[0].url) == "https://example.jobs.personio.com/xml"


@pytest.mark.parametrize("status", [404, 500, 302])
def test_http_errors_are_wrapped(status):
    connector, client = make_connector(status=status)
    try:
        with pytest.raises(PersonioConnectorError, match=str(status)):
            connector.fetch_jobs()
    finally:
        client.close()


@pytest.mark.parametrize(
    "body",
    [
        b"not xml",
        b"<rss></rss>",
        b'<!DOCTYPE x [<!ENTITY a "b">]><workzag-jobs/>',
        "<!DOCTYPE x><workzag-jobs/>".encode("utf-16"),
        b"<workzag-jobs><position><id>1</id></position></workzag-jobs>",
        pytest.param(b"x" * (20 * 1024 * 1024 + 1), id="too-large"),
    ],
)
def test_invalid_feeds_are_rejected(body):
    connector, client = make_connector(body=body)
    try:
        with pytest.raises(PersonioConnectorError):
            connector.fetch_jobs()
    finally:
        client.close()


def test_network_errors_are_wrapped():
    def boom(request):
        raise httpx.ConnectError("down", request=request)

    connector, client = make_connector(handler=boom)
    try:
        with pytest.raises(PersonioConnectorError, match="Could not reach"):
            connector.fetch_jobs()
    finally:
        client.close()


@pytest.mark.parametrize("company", ["", "a/b", "a.b", "-x"])
def test_company_slug_is_validated(company):
    with pytest.raises(ValueError):
        PersonioConnector(company)


def test_region_is_validated():
    with pytest.raises(ValueError, match="region"):
        PersonioConnector("example", region="evil.test/x")
