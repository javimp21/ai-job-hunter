from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ai_job_hunter.domain.normalized_job import (
    NormalizedJob,
    RemoteEligibility,
    RemotePolicy,
)


def test_normalized_job_applies_defaults_and_normalizes_simple_values() -> None:
    offer = NormalizedJob(
        provider=" example-board ",
        external_id="  role-42  ",
        title=" Backend Engineer ",
        company_name="  ",
        currency="eur",
    )

    assert offer.provider == "example-board"
    assert offer.external_id == "role-42"
    assert offer.company_name is None
    assert offer.currency == "EUR"
    assert offer.remote_eligibility is RemoteEligibility.UNKNOWN
    assert offer.remote_policy is None
    assert offer.discovered_at.tzinfo is UTC


def test_normalized_job_accepts_remote_and_salary_enums() -> None:
    offer = NormalizedJob(
        provider="example-board",
        title="Backend Engineer",
        remote_policy="REMOTE",
        remote_eligibility="EU_REMOTE",
        salary_min=Decimal("50000"),
        salary_max=Decimal("75000"),
    )

    assert offer.remote_policy is RemotePolicy.REMOTE
    assert offer.remote_eligibility is RemoteEligibility.EU_REMOTE


@pytest.mark.parametrize(
    "payload",
    [
        {"provider": "example-board", "title": "  "},
        {"provider": "example-board", "title": "Engineer", "currency": "EU"},
        {"provider": "example-board", "title": "Engineer", "salary_min": -1},
        {
            "provider": "example-board",
            "title": "Engineer",
            "salary_min": 80000,
            "salary_max": 70000,
        },
        {
            "provider": "example-board",
            "title": "Engineer",
            "published_at": datetime(2026, 9, 20),
        },
    ],
)
def test_normalized_job_rejects_invalid_data(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        NormalizedJob(**payload)
