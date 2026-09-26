"""Conservative outreach gating independent from job application decisions."""

from __future__ import annotations

from enum import StrEnum


class OutreachRecommendation(StrEnum):
    OUTREACH_RECOMMENDED = "OUTREACH_RECOMMENDED"
    OUTREACH_OPTIONAL = "OUTREACH_OPTIONAL"
    NO_OUTREACH = "NO_OUTREACH"


def _decision(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw).strip().upper()


def recommend_outreach(
    decision: object,
    priority: int | float | None,
    role_relevance: int | float | None,
    hard_mismatch: bool,
    application_status: str | None,
    existing_active_outreach: bool,
) -> OutreachRecommendation:
    """Return a rule-based recommendation; never alter APPLY/REVIEW/SKIP.

    Any existing application record or active outreach suppresses a *new*
    initial outreach recommendation. APPLY is recommended only when neither
    exists. REVIEW is optional at priority >= 70 and role relevance >= 0.75,
    provided there is no hard mismatch. SKIP and unknown decisions return NO.
    """

    if _decision(decision) == "SKIP":
        return OutreachRecommendation.NO_OUTREACH
    if application_status and str(application_status).strip():
        return OutreachRecommendation.NO_OUTREACH
    if existing_active_outreach:
        return OutreachRecommendation.NO_OUTREACH

    state = _decision(decision)
    if state == "APPLY":
        return OutreachRecommendation.OUTREACH_RECOMMENDED
    if (
        state == "REVIEW"
        and not hard_mismatch
        and priority is not None
        and role_relevance is not None
        and priority >= 70
        and role_relevance >= 0.75
    ):
        return OutreachRecommendation.OUTREACH_OPTIONAL
    return OutreachRecommendation.NO_OUTREACH


def outreach_recommendation_reasons(
    decision: object,
    priority: int | float | None,
    role_relevance: int | float | None,
    hard_mismatch: bool,
    application_status: str | None,
    existing_active_outreach: bool,
) -> tuple[str, ...]:
    """Explain the same deterministic gates used by :func:`recommend_outreach`."""

    result = recommend_outreach(
        decision,
        priority,
        role_relevance,
        hard_mismatch,
        application_status,
        existing_active_outreach,
    )
    if result is OutreachRecommendation.OUTREACH_RECOMMENDED:
        return ("APPLY with no application record and no active outreach.",)
    if result is OutreachRecommendation.OUTREACH_OPTIONAL:
        return (
            "REVIEW has priority >= 70 and role relevance >= 0.75.",
            "No strong mismatch, application record, or active outreach is present.",
        )

    reasons: list[str] = []
    state = _decision(decision)
    if state == "SKIP":
        reasons.append("SKIP decisions are not recommended for outreach.")
    if application_status and str(application_status).strip():
        reasons.append("An application record already exists.")
    if existing_active_outreach:
        reasons.append("Active outreach already exists.")
    if state == "REVIEW":
        if hard_mismatch:
            reasons.append("A strong mismatch is present.")
        if priority is None or priority < 70:
            reasons.append("REVIEW priority is below 70 or unavailable.")
        if role_relevance is None or role_relevance < 0.75:
            reasons.append("REVIEW role relevance is below 0.75 or unavailable.")
    if not reasons:
        reasons.append("Decision is not eligible under the conservative outreach rules.")
    return tuple(reasons)
