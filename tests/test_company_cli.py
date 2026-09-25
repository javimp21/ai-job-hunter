from __future__ import annotations

from sqlalchemy import create_engine

from ai_job_hunter import company_cli
from ai_job_hunter.db.base import Base
from ai_job_hunter.db.session import create_session_factory


def test_show_unknown_company_keeps_absent_facts_unknown(monkeypatch, capsys) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(company_cli, "create_database_engine", lambda settings: engine)
    monkeypatch.setattr(company_cli, "create_session_factory", create_session_factory)

    try:
        assert company_cli.main(["show", "Unlisted Example"]) == 0
    finally:
        engine.dispose()

    output = capsys.readouterr().out
    assert "Evidence: none in the imported sources" in output
    assert "Remote from Spain: UNKNOWN" in output
    assert "Public salary: UNKNOWN" in output
    assert "Company type: UNKNOWN" in output
