from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from ai_job_hunter.connectors import (
    JobConnector,
    TeamtailorConnector,
    TeamtailorConnectorError,
)
from ai_job_hunter.domain.normalized_job import RemoteEligibility, RemotePolicy

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:tt="https://teamtailor.com/locations">
  <channel>
    <title>Example</title>
    <link>https://example.teamtailor.com/jobs</link>
    <item>
      <title>Backend Engineer</title>
      <description>&lt;p&gt;Build &lt;strong&gt;APIs&lt;/strong&gt;.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Python&lt;/li&gt;&lt;/ul&gt;</description>
      <pubDate>Fri, 24 Jul 2026 09:05:16 +0200</pubDate>
      <link>https://example.teamtailor.com/jobs/1-backend-engineer</link>
      <remoteStatus>{status}</remoteStatus>
      <guid>guid-1</guid>
      <tt:locations>
        <tt:location>
          <tt:name>Madrid HQ</tt:name>
          <tt:address>Calle 1</tt:address>
          <tt:zip>28001</tt:zip>
          <tt:city>Madrid</tt:city>
          <tt:country>Spain</tt:country>
        </tt:location>
      </tt:locations>
      <tt:department>Engineering</tt:department>
      <tt:role>Backend</tt:role>
      <tt:division/>
    </item>
    <item>
      <title>Designer</title>
      <description></description>
      <pubDate>not a date</pubDate>
      <link>https://example.teamtailor.com/jobs/2-designer</link>
      <guid></guid>
    </item>
  </channel>
</rss>
"""


def feed(status: str = "fully") -> bytes:
    return FEED.replace("{status}", status).encode("utf-8")


def make_connector(*, handler=None, body: bytes | None = None, status=200, **kwargs):
    if handler is None:
        handler = lambda _request: httpx.Response(status, content=body if body is not None else feed())
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return TeamtailorConnector("example", client=client, **kwargs), client


def test_connector_reads_public_feed_and_normalizes_items():
    requests = []
    connector, client = make_connector(
        handler=lambda req: (requests.append(req), httpx.Response(200, content=feed()))[1],
        company_name="Example Co",
    )
    try:
        assert isinstance(connector, JobConnector)
        first, second = connector.fetch_jobs()
    finally:
        client.close()

    assert len(requests) == 1
    assert str(requests[0].url) == "https://example.teamtailor.com/jobs.rss"
    assert first.provider == "teamtailor"
    assert first.external_id == "guid-1"
    assert first.title == "Backend Engineer"
    assert first.company_name == "Example Co"
    assert first.source_url == "https://example.teamtailor.com/jobs/1-backend-engineer"
    assert first.description == "Build APIs.\nPython"
    assert first.location == "Madrid, Spain"
    assert first.remote_policy is RemotePolicy.REMOTE
    assert first.remote_eligibility is RemoteEligibility.UNKNOWN
    assert first.published_at == datetime(2026, 7, 24, 7, 5, 16, tzinfo=UTC)
    assert first.raw_metadata["department"] == "Engineering"

    # Missing guid falls back to the link; unparseable pubDate and absent fields stay unknown.
    assert second.external_id == "https://example.teamtailor.com/jobs/2-designer"
    assert second.description is None
    assert second.location is None
    assert second.remote_policy is None
    assert second.published_at is None


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("fully", RemotePolicy.REMOTE),
        ("hybrid", RemotePolicy.HYBRID),
        ("none", RemotePolicy.ONSITE),
        ("temporary", None),
        ("something-new", None),
    ],
)
def test_remote_status_mapping(status, expected):
    connector, client = make_connector(body=feed(status))
    try:
        assert connector.fetch_jobs()[0].remote_policy is expected
    finally:
        client.close()


def test_max_jobs_limits_items():
    connector, client = make_connector(max_jobs=1)
    try:
        assert len(connector.fetch_jobs()) == 1
    finally:
        client.close()


@pytest.mark.parametrize(
    "prefix",
    [
        b'<!DOCTYPE rss [<!ENTITY a "aaaa">]>',
        b"<!doctype rss>",
        b'<!ENTITY x "y">',
    ],
)
def test_dtd_and_entity_declarations_are_rejected(prefix):
    body = b'<?xml version="1.0"?>' + prefix + feed().split(b"?>", 1)[1]
    connector, client = make_connector(body=body)
    try:
        with pytest.raises(TeamtailorConnectorError, match="DTD"):
            connector.fetch_jobs()
    finally:
        client.close()


def test_utf16_doctype_is_rejected():
    body = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE rss><rss/>'.encode("utf-16")
    connector, client = make_connector(body=body)
    try:
        with pytest.raises(TeamtailorConnectorError, match="DTD"):
            connector.fetch_jobs()
    finally:
        client.close()


@pytest.mark.parametrize("body", [b"<rss><channel>", b"<html></html>"])
def test_invalid_or_non_rss_documents_raise(body):
    connector, client = make_connector(body=body)
    try:
        with pytest.raises(TeamtailorConnectorError):
            connector.fetch_jobs()
    finally:
        client.close()


def test_http_and_network_errors_do_not_leak_urls():
    connector, client = make_connector(status=503)
    try:
        with pytest.raises(TeamtailorConnectorError, match="HTTP 503") as http_error:
            connector.fetch_jobs()
    finally:
        client.close()
    assert "teamtailor.com" not in str(http_error.value)

    def boom(request):
        raise httpx.ConnectError("failed to reach https://example.teamtailor.com/jobs.rss", request=request)

    connector, client = make_connector(handler=boom)
    try:
        with pytest.raises(TeamtailorConnectorError) as network_error:
            connector.fetch_jobs()
    finally:
        client.close()
    assert "teamtailor.com" not in str(network_error.value)


def test_item_without_title_raises_without_leaking_content():
    body = b"<rss><channel><item><link>https://secret.example/x</link></item></channel></rss>"
    connector, client = make_connector(body=body)
    try:
        with pytest.raises(TeamtailorConnectorError, match="position 0") as error:
            connector.fetch_jobs()
    finally:
        client.close()
    assert "secret.example" not in str(error.value)


@pytest.mark.parametrize("company", ["", "  ", "a.b", "a/b", "exa mple", "-bad", "evil.com#"])
def test_company_must_be_a_subdomain_label(company):
    with pytest.raises(ValueError):
        TeamtailorConnector(company)
