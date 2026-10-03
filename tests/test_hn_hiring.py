import httpx
import pytest

from ai_job_hunter.company_leads import CompanyLeadsConfigError
from ai_job_hunter.hn_hiring import HNHiringError, fetch_latest_thread, leads_from_thread

THREAD = {
    "id": 1,
    "title": "Ask HN: Who is hiring? (October 2026)",
    "children": [
        {"id": 11, "text": 'Checkly | <a href="https://www.checklyhq.com">site</a> | Backend Engineer | REMOTE (Europe) | Full-time<p>'
                           'Apply: <a href="https://jobs.ashbyhq.com/checkly?utm_source=hn">jobs</a>'},
        {"id": 12, "text": 'River | Backend | REMOTE (US only) | <a href="https://jobs.ashbyhq.com/river">jobs</a>'},
        {"id": 13, "text": 'Acme (<a href="https://acme.example">acme</a>) | Engineer | Remote, worldwide<p>'
                           'Chat: <a href="https://acme.zulipchat.com/join/abc/">zulip</a> '
                           '<a href="https://acme.example/careers/backend?utm_campaign=x">role</a>'},
        {"id": 14, "text": 'Onsite Inc | Engineer | ONSITE Berlin'},
        {"id": 15, "text": None},
        {"id": 16, "text": "Location: Dubrovnik, Croatia | REMOTE (EU) | Engineer"},
        {"id": 17, "text": 'Company: Beta Labs | REMOTE (Europe) | <a href="https://beta.example">site</a>'},
    ],
}


def test_thread_becomes_reachable_remote_leads_with_provenance():
    leads = {lead.company_name: lead for lead in leads_from_thread(THREAD).leads}

    assert set(leads) == {"Checkly", "Acme", "Beta Labs"}
    checkly = leads["Checkly"]
    assert checkly.website_url == "https://www.checklyhq.com"
    assert checkly.careers_url == "https://jobs.ashbyhq.com/checkly"
    assert checkly.source_type == "hn_who_is_hiring"
    assert checkly.source_url == "https://news.ycombinator.com/item?id=11"
    assert "REMOTE (Europe)" in checkly.hiring_hint
    acme = leads["Acme"]
    assert acme.website_url == "https://acme.example"
    assert acme.careers_url == "https://acme.example/careers/backend"


def test_all_flag_keeps_non_remote_postings_and_empty_threads_fail():
    names = {lead.company_name for lead in leads_from_thread(THREAD, reachable_only=False).leads}
    assert {"River", "Onsite Inc"} <= names
    with pytest.raises(CompanyLeadsConfigError):
        leads_from_thread({"title": "x", "children": []})


def test_fetch_latest_thread_uses_search_then_item_and_reports_errors_safely():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("search_by_date"):
            return httpx.Response(200, json={"hits": [
                {"objectID": "2", "title": "Ask HN: Who wants to be hired? (October 2026)"},
                {"objectID": "1", "title": "Ask HN: Who is hiring? (October 2026)"},
            ]})
        assert request.url.path.endswith("/items/1")
        return httpx.Response(200, json=THREAD)

    thread = fetch_latest_thread(httpx.Client(transport=httpx.MockTransport(handler)))
    assert thread["title"].startswith("Ask HN: Who is hiring?")

    failing = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    with pytest.raises(HNHiringError, match="503"):
        fetch_latest_thread(failing)
