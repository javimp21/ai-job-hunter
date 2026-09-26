from ai_job_hunter.outreach.recommendations import (
    OutreachRecommendation,
    outreach_recommendation_reasons,
    recommend_outreach,
)


def _recommend(
    decision="APPLY",
    priority=80,
    role_relevance=0.9,
    hard_mismatch=False,
    application_status=None,
    existing_active_outreach=False,
):
    return recommend_outreach(
        decision,
        priority,
        role_relevance,
        hard_mismatch,
        application_status,
        existing_active_outreach,
    )


def test_apply_without_application_or_active_outreach_is_recommended():
    assert _recommend() is OutreachRecommendation.OUTREACH_RECOMMENDED


def test_strong_review_is_optional_but_weak_review_is_not():
    assert _recommend(decision="REVIEW") is OutreachRecommendation.OUTREACH_OPTIONAL
    assert _recommend(decision="REVIEW", priority=69) is OutreachRecommendation.NO_OUTREACH
    assert _recommend(decision="REVIEW", role_relevance=0.74) is OutreachRecommendation.NO_OUTREACH
    assert _recommend(decision="REVIEW", hard_mismatch=True) is OutreachRecommendation.NO_OUTREACH


def test_skip_and_application_or_active_outreach_suppress_new_outreach():
    assert _recommend(decision="SKIP") is OutreachRecommendation.NO_OUTREACH
    for status in ("DRAFT", "APPLIED", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN"):
        assert _recommend(application_status=status) is OutreachRecommendation.NO_OUTREACH
    assert _recommend(existing_active_outreach=True) is OutreachRecommendation.NO_OUTREACH


def test_recommendation_reason_helper_explains_thresholds():
    reasons = outreach_recommendation_reasons(
        "REVIEW", 72, 0.8, False, None, False
    )
    assert "priority >= 70" in reasons[0]
    assert "role relevance >= 0.75" in reasons[0]
