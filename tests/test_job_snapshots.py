import json
from datetime import UTC, datetime
from pathlib import Path

from ai_job_hunter.domain.normalized_job import NormalizedJob
from ai_job_hunter.snapshots import (
    JOB_SNAPSHOT_FORMAT,
    load_job_snapshot,
    load_remotive_snapshot,
    save_job_snapshot,
    save_remotive_snapshot,
)


def offer(provider: str, external_id: str) -> NormalizedJob:
    return NormalizedJob(
        provider=provider,
        external_id=external_id,
        source_url=f"https://jobs.example.test/{provider}/{external_id}",
        title="Backend Engineer",
        company_name="Fictional Systems",
        description="Build sample services with Python.",
        location="Spain",
        raw_metadata={"fixture": provider},
        published_at=datetime(2026, 9, 20, tzinfo=UTC),
        discovered_at=datetime(2026, 9, 24, tzinfo=UTC),
    )


def test_multi_source_snapshot_keeps_provider_metadata_and_replays(tmp_path: Path):
    offers = [offer("greenhouse", "gh-1"), offer("lever", "lv-1")]
    path = save_job_snapshot(tmp_path / "mixed.local.json", offers)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["format"] == JOB_SNAPSHOT_FORMAT
    assert [item["provider"] for item in payload["offers"]] == ["greenhouse", "lever"]
    assert load_job_snapshot(path) == offers
    assert [item.provider for item in load_job_snapshot(path)] == ["greenhouse", "lever"]


def test_generic_snapshot_loader_keeps_legacy_remotive_snapshots_readable(tmp_path: Path):
    remotive = offer("remotive", "rm-1")
    path = save_remotive_snapshot(tmp_path / "old-remotive.local.json", [remotive])

    assert load_remotive_snapshot(path) == [remotive]
    assert load_job_snapshot(path) == [remotive]
