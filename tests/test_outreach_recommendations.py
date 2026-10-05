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


def test_only_strong_apply_is_recommended_and_review_never_is():
    assert _recommend(priority=70) is OutreachRecommendation.OUTREACH_RECOMMENDED
    assert _recommend(priority=69) is OutreachRecommendation.NO_OUTREACH
    assert _recommend(priority=None) is OutreachRecommendation.NO_OUTREACH
    assert _recommend(decision="REVIEW") is OutreachRecommendation.NO_OUTREACH
    assert _recommend(decision="REVIEW", priority=95, role_relevance=1.0) is OutreachRecommendation.NO_OUTREACH


def test_skip_and_application_or_active_outreach_suppress_new_outreach():
    assert _recommend(decision="SKIP") is OutreachRecommendation.NO_OUTREACH
    for status in ("DRAFT", "APPLIED", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN"):
        assert _recommend(application_status=status) is OutreachRecommendation.NO_OUTREACH
    assert _recommend(existing_active_outreach=True) is OutreachRecommendation.NO_OUTREACH


def test_recommendation_reason_helper_explains_thresholds():
    assert "priority >= 70" in outreach_recommendation_reasons("APPLY", 72, 0.8, False, None, False)[0]
    assert "below 70" in outreach_recommendation_reasons("APPLY", 60, 0.8, False, None, False)[0]
    assert "REVIEW is not" in outreach_recommendation_reasons("REVIEW", 90, 0.9, False, None, False)[0]
