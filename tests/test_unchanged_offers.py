from datetime import UTC, datetime

from ai_job_hunter.services.ingestion import ingest_job, known_unchanged_sources


def test_only_offers_with_the_same_content_as_an_open_stored_source_are_unchanged(db_session, fake_offer_batch) -> None:
    original, _, refreshed = fake_offer_batch
    stored = ingest_job(db_session, original)
    key = (original.provider, original.external_id)

    assert known_unchanged_sources(db_session, [original]) == {key: (stored.job_id, stored.job_source_id)}

    # The same posting with another description or salary is a change: it must be processed again.
    assert known_unchanged_sources(db_session, [refreshed]) == {}
    changed_title = original.model_copy(update={"title": "A different title"})
    assert known_unchanged_sources(db_session, [changed_title]) == {}

    # Offers the database has never seen, or without a provider id, are never skipped.
    unseen = original.model_copy(update={"external_id": "never-seen"})
    no_id = original.model_copy(update={"external_id": None})
    assert known_unchanged_sources(db_session, [unseen, no_id]) == {}


def test_a_closed_source_is_never_listed_so_that_it_gets_reopened_by_a_normal_ingestion(
    db_session, fake_offer_batch
) -> None:
    from ai_job_hunter.models import JobSource

    original = fake_offer_batch[0]
    stored = ingest_job(db_session, original)
    db_session.get(JobSource, stored.job_source_id).closed_at = datetime(2026, 10, 1, tzinfo=UTC)
    db_session.commit()

    assert known_unchanged_sources(db_session, [original]) == {}
