from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, func, select

from ai_job_hunter import lead_refresh
from ai_job_hunter.company_leads_cli import main as leads_cli_main
from ai_job_hunter.company_sources import CompanyEvidenceRecord, CompanySourceBatch
from ai_job_hunter.config import Settings
from ai_job_hunter.db.base import Base
from ai_job_hunter.db.session import create_session_factory
from ai_job_hunter.domain.company_intelligence import CompanyEvidenceType
from ai_job_hunter.hn_hiring import fetch_latest_thread
from ai_job_hunter.models import CompanyLead

NOW = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
POSTED = datetime(2026, 10, 1, 16, 0, tzinfo=UTC)
THREAD = {
    "id": 77,
    "title": "Ask HN: Who is hiring? (October 2026)",
    "children": [
        {"id": 11, "text": 'Checkly | <a href="https://www.checklyhq.com">site</a> | Backend | REMOTE (Europe)'},
    ],
}


def test_hn_thread_is_reimported_until_it_has_settled():
    state: dict = {}
    assert lead_refresh.hn_thread_needs_import("77", POSTED, state)

    lead_refresh.record_hn_thread(state, "77", now=POSTED + timedelta(days=1))
    assert lead_refresh.hn_thread_needs_import("77", POSTED, state)  # comments still arriving

    lead_refresh.record_hn_thread(state, "77", now=POSTED + timedelta(days=8))
    assert not lead_refresh.hn_thread_needs_import("77", POSTED, state)
    assert lead_refresh.hn_thread_needs_import("78", POSTED + timedelta(days=31), state)  # next month


def test_directory_reimports_on_change_or_after_thirty_days():
    state: dict = {}
    assert lead_refresh.directory_needs_import("p", "a", state, now=NOW)
    lead_refresh.record_directory(state, "p", "a", imported=True, now=NOW)

    assert not lead_refresh.directory_needs_import("p", "a", state, now=NOW + timedelta(days=29))
    assert lead_refresh.directory_needs_import("p", "b", state, now=NOW + timedelta(days=1))
    assert lead_refresh.directory_needs_import("p", "a", state, now=NOW + timedelta(days=30))

    lead_refresh.record_directory(state, "p", "ignored", imported=False, now=NOW + timedelta(days=5))
    assert state["directories"]["p"]["sha256"] == "a"  # a skipped check keeps the last imported hash
    assert not lead_refresh.directories_check_due(["p"], state, now=NOW + timedelta(days=6))
    assert lead_refresh.directories_check_due(["p"], state, now=NOW + timedelta(days=12))
    assert lead_refresh.directories_check_due(["p", "other"], state, now=NOW)


def test_state_file_round_trip_and_corrupt_file_is_empty(tmp_path):
    path = tmp_path / "nested" / "state.json"
    assert lead_refresh.load_state(path) == {}
    lead_refresh.save_state({"hn_threads": {"1": {}}}, path)
    assert lead_refresh.load_state(path) == {"hn_threads": {"1": {}}}
    path.write_text("not json", encoding="utf-8")
    assert lead_refresh.load_state(path) == {}


def _hn_client(item_requests: list[str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("search_by_date"):
            return httpx.Response(200, json={"hits": [
                {"objectID": "77", "title": "Ask HN: Who is hiring? (October 2026)",
                 "created_at_i": int(POSTED.timestamp())},
            ]})
        item_requests.append(request.url.path)
        return httpx.Response(200, json=THREAD)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_latest_thread_skips_the_download_when_not_needed():
    seen = []
    items: list[str] = []
    assert fetch_latest_thread(_hn_client(items), needs_import=lambda i, t: seen.append((i, t)) or False) is None
    assert items == []
    assert seen == [("77", POSTED)]

    assert fetch_latest_thread(_hn_client(items), needs_import=lambda i, t: True)["id"] == 77
    assert items == ["/api/v1/items/77"]


@pytest.fixture
def cli_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'cli.db').as_posix()}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr("ai_job_hunter.company_leads_cli.get_settings", lambda: Settings())
    monkeypatch.setattr("ai_job_hunter.company_leads_cli.create_database_engine", lambda _settings: engine)
    return engine


def _lead_count(engine) -> int:
    with create_session_factory(engine)() as session:
        return session.scalar(select(func.count()).select_from(CompanyLead))


def test_cli_import_hn_new_only_imports_once_the_thread_has_settled(cli_db, tmp_path, monkeypatch, capsys):
    state_file = tmp_path / "state.json"
    calls: list[bool] = []

    def fake_fetch(client=None, *, needs_import=None):
        calls.append(needs_import is not None)
        if needs_import is not None and not needs_import("77", POSTED):
            return None
        return THREAD

    monkeypatch.setattr("ai_job_hunter.company_leads_cli.fetch_latest_thread", fake_fetch)
    args = ["import-hn", "--new-only", "--state-file", str(state_file)]
    clock = {"now": POSTED + timedelta(days=1)}

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    monkeypatch.setattr("ai_job_hunter.company_leads_cli.datetime", FrozenDateTime)
    monkeypatch.setattr(lead_refresh, "datetime", FrozenDateTime)

    assert leads_cli_main(args) == 0
    assert _lead_count(cli_db) == 1
    # Posted one day ago: not settled yet, so it is imported again (deduplicated).
    assert leads_cli_main(args) == 0
    assert _lead_count(cli_db) == 1
    assert "DUPLICATES 1" in capsys.readouterr().out

    clock["now"] = POSTED + timedelta(days=9)
    assert leads_cli_main(args) == 0  # settled import recorded
    capsys.readouterr()
    assert leads_cli_main(args) == 0
    assert "already imported" in capsys.readouterr().out
    assert calls == [True] * 4


def test_cli_import_hn_without_flag_always_downloads(cli_db, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "ai_job_hunter.company_leads_cli.fetch_latest_thread",
        lambda client=None, *, needs_import=None: calls.append(needs_import) or THREAD,
    )
    assert leads_cli_main(["import-hn", "--state-file", str(tmp_path / "s.json")]) == 0
    assert calls == [None]


def _batch(provider: str, sha: str) -> CompanySourceBatch:
    record = CompanyEvidenceRecord(
        provider=provider, evidence_type=CompanyEvidenceType.COMPENSATION, source_key=f"{provider}-acme",
        company_name="Acme Directory", source_url="https://github.example.test/readme",
        structured_data={"career_page_urls": ["https://jobs.lever.co/acmedirectory"], "public_salary": True},
    )
    return CompanySourceBatch(
        provider=provider, readme_url="https://github.example.test/readme", repository_url="r",
        license_name="l", license_url="u", fetched_at=NOW, body_sha256=sha, source_file_sha=None,
        snapshot_path=Path("x"), records=(record,),
    )


def test_cli_import_directories_if_due_only_imports_changed_sources(cli_db, tmp_path, monkeypatch, capsys):
    state_file = tmp_path / "state.json"
    refreshes = []
    sha = {"value": "v1"}

    def fake_refresh(*, offline=False, **_kwargs):
        refreshes.append(offline)
        return (_batch("manfred_public_salary_companies", sha["value"]),), ()

    monkeypatch.setattr("ai_job_hunter.company_leads_cli.refresh_company_source_snapshots", fake_refresh)
    args = ["import-directories", "--directory", "manfred", "--if-due", "--state-file", str(state_file)]

    assert leads_cli_main(args) == 0
    assert _lead_count(cli_db) == 1
    assert "CREATED 1" in capsys.readouterr().out
    # Checked within the last week: no download at all.
    assert leads_cli_main(args) == 0
    assert len(refreshes) == 1
    assert "checked recently" in capsys.readouterr().out

    # Age the check so the source is looked at again; unchanged content is not re-imported.
    state = lead_refresh.load_state(state_file)
    state["directories"]["manfred_public_salary_companies"]["checked_at"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    lead_refresh.save_state(state, state_file)
    assert leads_cli_main(args) == 0
    assert len(refreshes) == 2
    assert "nothing to do" in capsys.readouterr().out

    # Changed content triggers an import.
    state["directories"]["manfred_public_salary_companies"]["checked_at"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    lead_refresh.save_state(state, state_file)
    sha["value"] = "v2"
    assert leads_cli_main(args) == 0
    assert "DUPLICATES 1" in capsys.readouterr().out
    assert lead_refresh.load_state(state_file)["directories"]["manfred_public_salary_companies"]["sha256"] == "v2"


def test_cli_import_directories_if_due_reports_fetch_failure(cli_db, tmp_path, monkeypatch, capsys):
    def failing(*, offline=False, **_kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr("ai_job_hunter.company_leads_cli.refresh_company_source_snapshots", failing)
    code = leads_cli_main(["import-directories", "--if-due", "--state-file", str(tmp_path / "s.json")])
    assert code == 2
    assert "directory refresh failed (ConnectError)" in capsys.readouterr().err
