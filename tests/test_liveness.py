from dataclasses import replace
from uuid import uuid4

import httpx

from ai_job_hunter.decision_engine import FinalDecision
from ai_job_hunter.services.liveness import PostingLiveness, needs_check, page_says_closed

PUBLIC = lambda host, port: ("93.184.216.34",)  # noqa: E731


def check(handler, url):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return PostingLiveness(client, resolver=PUBLIC)(url)


def test_closing_wording_in_several_languages_is_recognised_and_live_copy_is_not():
    assert page_says_closed("<p>No longer accepting applications</p>")
    assert page_says_closed("<h1>Esta oferta ya no está disponible</h1>")
    assert page_says_closed("<p>The job you are trying to apply for has been filled.</p>")
    assert page_says_closed("<p>Deze vacature is gesloten</p>")
    assert not page_says_closed("<p>Once the application form has been filled you will hear from us.</p>")
    assert not page_says_closed("<p>This role is closed-loop control of the platform.</p>")
    assert not page_says_closed("<script>var t='no longer accepting applications'</script><p>Apply now</p>")


def test_only_aggregator_hosts_are_checked():
    assert needs_check("https://www.adzuna.es/details/1") and needs_check("https://remotive.com/remote-jobs/1")
    assert not needs_check("https://www.linkedin.com/jobs/view/1/")  # its terms forbid automated access
    assert not needs_check("https://job-boards.greenhouse.io/acme/jobs/1") and not needs_check(None)


def test_status_and_page_text_decide_and_everything_else_is_unknown():
    url = "https://www.adzuna.es/details/1"
    assert check(lambda r: httpx.Response(404), url) is False
    assert check(lambda r: httpx.Response(200, text="<p>No longer accepting applications</p>"), url) is False
    assert check(lambda r: httpx.Response(200, text="<p>Apply for Backend Engineer</p>"), url) is True
    assert check(lambda r: httpx.Response(429), url) is None  # rate limited
    assert check(lambda r: httpx.Response(503), url) is None
    assert check(lambda r: (_ for _ in ()).throw(httpx.ConnectError("x")), url) is None
    assert PostingLiveness(resolver=PUBLIC)("https://job-boards.greenhouse.io/acme/jobs/1") is None  # not an aggregator


def test_redirects_are_followed_a_few_hops_and_private_targets_are_never_fetched():
    url = "https://www.adzuna.es/details/1"
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.path.startswith("/details"):
            return httpx.Response(302, headers={"location": "https://www.adzuna.es/gone"})
        return httpx.Response(410)

    assert check(handler, url) is False and len(seen) == 2

    client = httpx.Client(transport=httpx.MockTransport(lambda r: pytest_fail()))
    private = PostingLiveness(client, resolver=lambda host, port: ("10.0.0.5",))
    assert private(url) is None


def pytest_fail():
    raise AssertionError("a private address must not be requested")


def test_a_closed_posting_is_suppressed_and_unknown_or_open_ones_are_not():
    from test_notifications import _opportunity  # noqa: PLC0415 - shared fixture builder

    from ai_job_hunter.services.notifications import _closed_posting_suppression

    item = replace(_opportunity(uuid4(), FinalDecision.REVIEW, 80), url="https://www.adzuna.es/details/1")

    assert _closed_posting_suppression(item, lambda url: False) == "posting_no_longer_available"
    assert _closed_posting_suppression(item, lambda url: True) is None
    assert _closed_posting_suppression(item, lambda url: None) is None
    assert _closed_posting_suppression(item, None) is None
