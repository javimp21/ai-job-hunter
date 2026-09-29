"""Conservative form-field classification and value-free autofill plans."""

from __future__ import annotations

from decimal import Decimal
import re

from ai_job_hunter.application_prep.browser.models import (
    AnswerPolicy,
    ApplicationFormSnapshot,
    CanonicalField,
    FieldMapping,
    FormField,
    FormFieldType,
    MappingConfidence,
)
from ai_job_hunter.application_prep.configuration import CandidateApplicationFacts
from ai_job_hunter.application_prep.models import (
    ApplicationPackage,
    ApplicationQuestion,
    ApplicationQuestionHandling,
    ApplicationQuestionType,
    CandidateDocument,
    CandidateDocumentType,
    CandidateWritingStyle,
)
from ai_job_hunter.application_prep.drafting import draft_answers
from ai_job_hunter.application_prep.service import recommend_cv_variant
from ai_job_hunter.candidates.profile import CandidateConfig
from ai_job_hunter.domain.normalized_job import SalaryPeriod
from ai_job_hunter.outreach.projects import CandidateProject


_LEGAL_RE = re.compile(
    r"\b(?:work authorization|authorized to work|right to work|work permit|visa|"
    r"sponsorship|criminal|convict(?:ed|ion)?|background check|legally work|citizenship|contact me|permission to contact|"
    r"terms(?: and conditions)?|consent|certify|attest|declar(?:e|ation))\b",
    re.I,
)
_SENSITIVE_RE = re.compile(
    r"\b(?:race|ethnicity|gender|sex|sexual orientation|disability|veteran|military|"
    r"religion|marital status|date of birth|birth date|health|medical|pregnan(?:t|cy)|national origin|eeo)\b",
    re.I,
)
_OPTIONAL_SELF_ID_RE = re.compile(
    r"\b(?:voluntary|optional|self.identification|prefer not to say|prefer not to disclose)\b", re.I
)
_SALARY_RE = re.compile(r"\b(?:salary|compensation|remuneration|desired pay|expected pay)\b", re.I)
_PREVIOUS_OLX_RE = re.compile(
    r"\b(?:(?:have you )?(?:ever |previously |in the past )?worked at olx|"
    r"(?:have you )?(?:ever |previously |in the past )?worked for (?:an? )?olx(?: group)? company|"
    r"(?:have you )?(?:ever |previously )?been employed by olx|previous employment at olx)\b",
    re.I,
)
_SPAIN_STATUS_RE = re.compile(r"\b(?:currently|already|based|located|living|residing)\b.{0,45}\bspain\b|\bspain\b.{0,30}\b(?:currently|already)\b", re.I)
_REGION_RE = re.compile(
    r"^(?:region|geographic region|continent|what region do you live in|which region are you based in|"
    r"what is the region you are located in)\??$",
    re.I,
)
_LOCATION_RE = re.compile(r"^(?:location|current location|city,? country|city and country)$", re.I)
_PREVIOUS_EMPLOYMENT_RE = re.compile(r"\b(?:previous|prior|past) employment\b|\b(?:have you )?worked at (?:the )?company before\b", re.I)
_RELOCATION_RE = re.compile(r"\brelocat(?:e|ion|ing)\b", re.I)
_NOTICE_PERIOD_RE = re.compile(r"\bnotice period\b", re.I)
_GO_TO_LANGUAGE_RE = re.compile(r"\b(?:go.to|preferred|primary) programming language\b", re.I)
_HISTORICAL_SALARY_RE = re.compile(
    r"\b(?:current|previous|past|last|former)\s+(?:base\s+)?(?:salary|compensation|pay)\b|"
    r"\b(?:salary|compensation|pay)\s+(?:history|details|in the past)\b|"
    r"\b(?:last drawn|previously earned)\s+(?:salary|compensation|pay)\b",
    re.I,
)
_CV_RE = re.compile(r"\b(?:cv|resume|curriculum vitae)\b", re.I)
_COVER_RE = re.compile(r"\bcover letter\b", re.I)
_CUSTOM_TEXT_RE = re.compile(
    r"\b(?:why|tell us|describe|explain|project|experience with|interested)\b|"
    r"\byears?\b.*\bexperience\b|\bexperience\b.*\byears?\b",
    re.I,
)

_EXACT_LABELS: dict[CanonicalField, set[str]] = {
    CanonicalField.FIRST_NAME: {"first name", "given name", "forename"},
    CanonicalField.LAST_NAME: {"last name", "family name", "surname"},
    CanonicalField.FULL_NAME: {"full name", "name"},
    CanonicalField.EMAIL: {"email", "email address", "e-mail", "e-mail address"},
    CanonicalField.PHONE: {"phone", "phone number", "mobile phone", "telephone"},
    CanonicalField.CITY: {"city", "current city", "town"},
    CanonicalField.COUNTRY: {"country", "current country", "country region", "country or region"},
    CanonicalField.CURRENT_ROLE: {"current role", "current position"},
    CanonicalField.CURRENT_COMPANY: {"current company", "current employer"},
    CanonicalField.OVERALL_EXPERIENCE_YEARS: {
        "years of experience", "total years of experience", "overall experience in years",
        "total experience (years)", "overall years of experience",
    },
    CanonicalField.LINKEDIN: {"linkedin", "linkedin url", "linkedin profile", "linkedin profile url"},
    CanonicalField.GITHUB: {"github", "github url", "github profile", "github profile url"},
    CanonicalField.PORTFOLIO: {"portfolio", "portfolio url", "personal website", "website"},
}
_SOURCE_KEYS: dict[CanonicalField, str] = {
    CanonicalField.FIRST_NAME: "facts.first_name",
    CanonicalField.LAST_NAME: "facts.last_name",
    CanonicalField.EMAIL: "facts.email",
    CanonicalField.PHONE: "facts.phone",
    CanonicalField.CITY: "derived.current_city",
    CanonicalField.COUNTRY: "derived.current_country",
    CanonicalField.CURRENT_ROLE: "profile.current_role",
    CanonicalField.CURRENT_COMPANY: "facts.current_company",
    CanonicalField.OVERALL_EXPERIENCE_YEARS: "profile.years_of_experience",
    CanonicalField.LINKEDIN: "facts.linkedin_url",
    CanonicalField.GITHUB: "facts.github_url",
    CanonicalField.PORTFOLIO: "facts.portfolio_url",
}


def _document_recommendation(
    canonical: CanonicalField,
    *,
    package: ApplicationPackage,
    documents: tuple[CandidateDocument, ...],
) -> str:
    if canonical is CanonicalField.CV:
        if documents:
            selected = recommend_cv_variant(
                package.job_title,
                package.technologies,
                package.requirements,
                documents,
            )
            if selected:
                return selected
        cv_documents = [item for item in documents if item.type is CandidateDocumentType.CV]
        if len(cv_documents) == 1:
            return cv_documents[0].display_name
    elif canonical is CanonicalField.COVER_LETTER:
        cover_letters = [item for item in documents if item.type is CandidateDocumentType.COVER_LETTER]
        if len(cover_letters) == 1:
            return cover_letters[0].display_name
        if len(cover_letters) > 1:
            return "Choose one of the configured cover letters during manual review."
    elif canonical is CanonicalField.PORTFOLIO_DOCUMENT:
        portfolios = [item for item in documents if item.type is CandidateDocumentType.PORTFOLIO]
        if len(portfolios) == 1:
            return portfolios[0].display_name
        if len(portfolios) > 1:
            return "Choose one of the configured portfolio documents during manual review."
    if canonical is CanonicalField.CV:
        return "NO_CV_CONFIGURED. Add CV metadata to candidate_documents.local.json; no file will be uploaded."
    return "No matching local document metadata is configured."


def _fold(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]+", " ", value.casefold())).strip()


def _salary_suggestion(candidate: CandidateConfig) -> str | None:
    preferences = candidate.preferences
    amount: Decimal | None = preferences.target_salary or preferences.minimum_salary
    if amount is None or preferences.salary_currency is None or preferences.salary_period is None:
        return None
    period = {
        SalaryPeriod.HOUR: "hour",
        SalaryPeriod.DAY: "day",
        SalaryPeriod.WEEK: "week",
        SalaryPeriod.MONTH: "month",
        SalaryPeriod.YEAR: "year",
    }[preferences.salary_period]
    rendered = format(amount.normalize(), 'f')
    amount_kind = "target" if preferences.target_salary is not None else "minimum"
    if preferences.salary_period is SalaryPeriod.YEAR:
        monthly = format((amount / Decimal(12)).normalize(), 'f')
        return (
            f"SALARY_INPUT_REQUIRED: {amount_kind} annual {preferences.salary_currency} {rendered}; "
            f"monthly equivalent {preferences.salary_currency} {monthly} (annual / 12). "
            "Payment schedule (12 vs 14 payments) is unknown; enter manually."
        )
    return f"SALARY_INPUT_REQUIRED: configured {amount_kind} {preferences.salary_currency} {rendered} per {period}; enter manually."


def _question_type(field: FormField) -> ApplicationQuestionType:
    return {
        FormFieldType.TEXT: ApplicationQuestionType.TEXT,
        FormFieldType.EMAIL: ApplicationQuestionType.EMAIL,
        FormFieldType.PHONE: ApplicationQuestionType.PHONE,
        FormFieldType.URL: ApplicationQuestionType.URL,
        FormFieldType.NUMBER: ApplicationQuestionType.NUMBER,
        FormFieldType.DATE: ApplicationQuestionType.DATE,
        FormFieldType.SELECT: ApplicationQuestionType.SELECT,
        FormFieldType.MULTISELECT: ApplicationQuestionType.MULTISELECT,
        FormFieldType.CHECKBOX: ApplicationQuestionType.YES_NO,
        FormFieldType.RADIO: ApplicationQuestionType.SELECT,
        FormFieldType.TEXTAREA: ApplicationQuestionType.TEXTAREA,
        FormFieldType.FILE: ApplicationQuestionType.FILE,
    }.get(field.field_type, ApplicationQuestionType.UNKNOWN)


def _classify(field: FormField) -> tuple[CanonicalField, MappingConfidence, tuple[str, ...]]:
    label = _fold(field.label)
    if _PREVIOUS_OLX_RE.search(field.label):
        return CanonicalField.PREVIOUS_EMPLOYMENT, MappingConfidence.HIGH, ("The label explicitly asks about prior employment at OLX.",)
    if _REGION_RE.fullmatch(field.label.strip()):
        return CanonicalField.REGION, MappingConfidence.HIGH, ("The label explicitly asks for a geographic region.",)
    if _LOCATION_RE.fullmatch(field.label.strip()):
        return CanonicalField.LOCATION, MappingConfidence.HIGH, ("The label asks for a city and country using explicit candidate facts.",)
    if _GO_TO_LANGUAGE_RE.search(field.label):
        return CanonicalField.PREFERRED_PROGRAMMING_LANGUAGE, MappingConfidence.HIGH, ("The label asks for a subjective preferred programming language.",)
    if _PREVIOUS_EMPLOYMENT_RE.search(field.label):
        return CanonicalField.PREVIOUS_EMPLOYMENT, MappingConfidence.HIGH, ("The label asks about prior employment; only an explicit local answer may be used.",)
    if _RELOCATION_RE.search(field.label):
        return CanonicalField.RELOCATION, MappingConfidence.HIGH, ("The label asks about relocation; search preferences are not treated as an answer.",)
    if _NOTICE_PERIOD_RE.search(field.label):
        return CanonicalField.NOTICE_PERIOD, MappingConfidence.HIGH, ("The label explicitly asks about notice period.",)
    if _LEGAL_RE.search(field.label):
        canonical = CanonicalField.WORK_AUTHORIZATION if re.search(r"work|visa|sponsor|citizenship", label) else CanonicalField.LEGAL_DECLARATION
        return canonical, MappingConfidence.HIGH, ("The label explicitly names a legal or work-authorization topic.",)
    if _SENSITIVE_RE.search(field.label):
        return CanonicalField.OPTIONAL_SELF_IDENTIFICATION, MappingConfidence.HIGH, ("The label explicitly names sensitive personal information.",)
    if _OPTIONAL_SELF_ID_RE.search(field.label):
        return CanonicalField.OPTIONAL_SELF_IDENTIFICATION, MappingConfidence.HIGH, ("The label marks this as optional self-identification.",)
    if _SPAIN_STATUS_RE.search(field.label):
        return CanonicalField.CURRENTLY_IN_SPAIN, MappingConfidence.HIGH, ("The label explicitly asks whether the candidate is currently in Spain.",)
    if _SALARY_RE.search(field.label) and not _HISTORICAL_SALARY_RE.search(field.label):
        return CanonicalField.SALARY_EXPECTATION, MappingConfidence.HIGH, ("The label explicitly asks about salary or compensation.",)
    if field.field_type is FormFieldType.FILE:
        if _COVER_RE.search(field.label) and _CV_RE.search(field.label):
            canonical = CanonicalField.OTHER_DOCUMENT
        elif _COVER_RE.search(field.label):
            canonical = CanonicalField.COVER_LETTER
        elif _CV_RE.search(field.label):
            canonical = CanonicalField.CV
        elif re.search(r"\bportfolio\b", field.label, re.I):
            canonical = CanonicalField.PORTFOLIO_DOCUMENT
        else:
            canonical = CanonicalField.OTHER_DOCUMENT
        return canonical, MappingConfidence.HIGH, ("The visible control or label requests a document.",)
    if _CV_RE.search(field.label):
        return CanonicalField.CV, MappingConfidence.HIGH, ("The label explicitly refers to a CV or resume.",)
    if _COVER_RE.search(field.label):
        return CanonicalField.COVER_LETTER, MappingConfidence.HIGH, ("The label explicitly requests a cover letter.",)
    for canonical, labels in _EXACT_LABELS.items():
        if label in labels:
            if field.label_source in {"label", "aria"}:
                return canonical, MappingConfidence.HIGH, ("The visible label is an exact match for this configured fact.",)
            return canonical, MappingConfidence.MEDIUM, ("The control hint matches a known field name, but has no explicit visible label.",)
    if label in {"location", "current location", "address", "city country"}:
        return CanonicalField.LOCATION, MappingConfidence.HIGH, ("The label asks for a location, whose expected format is ambiguous.",)
    if _CUSTOM_TEXT_RE.search(field.label):
        return CanonicalField.CUSTOM_QUESTION, MappingConfidence.MEDIUM, ("The label reads as a free-text application question.",)
    return CanonicalField.UNKNOWN, MappingConfidence.LOW, ("No unambiguous field label was recognized.",)


def _configured_value(
    source_key: str | None,
    candidate: CandidateConfig,
    facts: CandidateApplicationFacts,
) -> str | None:
    if source_key is None:
        return None
    scope, key = source_key.split(".", maxsplit=1)
    if scope == "derived":
        city = facts.current_city or candidate.profile.current_city
        country = facts.current_country or candidate.profile.current_country
        if key == "current_city":
            value = city
        elif key == "current_country":
            value = country
        elif key == "full_name":
            value = f"{facts.first_name} {facts.last_name}" if facts.first_name and facts.last_name else None
        elif key == "current_location":
            value = f"{city}, {country}" if city and country else None
        elif key == "region":
            value = "Europe" if country and country.casefold() == "spain" else None
        elif key == "currently_in_spain":
            value = "Yes" if country and country.casefold() == "spain" else None
        else:
            value = None
    else:
        value = getattr(facts if scope == "facts" else candidate.profile, key, None)
    if value is None or value == "":
        return None
    return format(value.normalize(), "f") if isinstance(value, Decimal) else str(value)


def _explicit_response(field: FormField, value: str | None) -> str | None:
    """Use an explicitly configured answer only when it fits the visible options."""
    if value is None:
        return None
    if field.options:
        option = next((item for item in field.options if item.casefold() == value.casefold()), None)
        return option
    return value if field.field_type in {FormFieldType.TEXT, FormFieldType.TEXTAREA, FormFieldType.SELECT} else None


def map_form_fields(
    snapshot: ApplicationFormSnapshot,
    *,
    candidate: CandidateConfig,
    facts: CandidateApplicationFacts,
    package: ApplicationPackage,
    projects: tuple[CandidateProject, ...] = (),
    documents: tuple[CandidateDocument, ...] = (),
) -> tuple[FieldMapping, ...]:
    mappings: list[FieldMapping] = []
    for field in snapshot.fields:
        canonical, confidence, evidence = _classify(field)
        source_key = _SOURCE_KEYS.get(canonical)
        if canonical is CanonicalField.FULL_NAME:
            source_key = "derived.full_name"
        elif canonical is CanonicalField.LOCATION:
            source_key = "derived.current_location"
        elif canonical is CanonicalField.REGION:
            source_key = "derived.region"
        elif canonical is CanonicalField.CURRENTLY_IN_SPAIN:
            source_key = "derived.currently_in_spain"
        elif canonical is CanonicalField.PREVIOUS_EMPLOYMENT:
            source_key = "facts.previous_employment"
        elif canonical is CanonicalField.RELOCATION:
            source_key = "facts.relocation_response"
        elif canonical is CanonicalField.NOTICE_PERIOD:
            source_key = "facts.notice_period"
        if source_key is not None:
            value = _configured_value(source_key, candidate, facts)
            value_evidence: tuple[str, ...] = (f"Value exists in {source_key}.",) if value else ("No explicit value is configured for this field.",)
            if canonical is CanonicalField.REGION and value:
                value_evidence = ("The configured current country is Spain, which maps to Europe for this explicit region question.",)
            elif canonical is CanonicalField.CURRENTLY_IN_SPAIN and value:
                value_evidence = ("The configured current country is Spain; only this explicit location question is answered.",)
            if canonical is CanonicalField.PREVIOUS_EMPLOYMENT:
                value = _explicit_response(field, value)
            elif canonical is CanonicalField.RELOCATION:
                value = _explicit_response(field, value)
                country = facts.current_country or candidate.profile.current_country
                already_in_spain = next(
                    (option for option in field.options if _fold(option) == "i am in spain already"),
                    None,
                )
                if value is None and country and country.casefold() == "spain":
                    value = already_in_spain
                    if value:
                        source_key = "profile.current_country" if not facts.current_country else "facts.current_country"
                        value_evidence = ("The configured current country is Spain, and this option explicitly states the candidate is already there; no relocation willingness is inferred.",)
                else:
                    value = _explicit_response(field, value)
                    if value:
                        value_evidence = ("This answer was explicitly configured in candidate_application.local.json.",)
            elif canonical is CanonicalField.CURRENTLY_IN_SPAIN:
                value = _explicit_response(field, value)
            elif canonical is CanonicalField.REGION:
                value = _explicit_response(field, value)
            if value is None and not (canonical is CanonicalField.REGION and value_evidence[0].startswith("The configured")):
                value_evidence = ("No explicit value is configured that matches the visible field choices.",)
            value_type_ok = field.field_type in {
                FormFieldType.TEXT, FormFieldType.EMAIL, FormFieldType.PHONE,
                FormFieldType.URL, FormFieldType.NUMBER, FormFieldType.SELECT, FormFieldType.RADIO,
            }
            option_match = not field.options or value is None or any(option.casefold() == value.casefold() for option in field.options)
            policy = (
                AnswerPolicy.SAFE_AUTO_FILL
                if confidence is MappingConfidence.HIGH and value and value_type_ok and option_match
                else AnswerPolicy.NEEDS_USER_INPUT
            )
            mappings.append(FieldMapping(
                field_id=field.id,
                canonical_field=canonical,
                confidence=confidence,
                evidence=evidence + value_evidence,
                source_label=field.label,
                answer_policy=policy,
                source_key=source_key if policy is AnswerPolicy.SAFE_AUTO_FILL else None,
            ))
            continue

        if canonical is CanonicalField.PREFERRED_PROGRAMMING_LANGUAGE:
            languages = (*candidate.profile.primary_skills, *candidate.profile.secondary_skills, *candidate.profile.technologies)
            java = next((item for item in languages if item.casefold() == "java"), None)
            mappings.append(FieldMapping(
                field_id=field.id,
                canonical_field=canonical,
                confidence=confidence,
                evidence=evidence + (("Java is explicitly listed in the candidate profile; this preference is subjective and requires review.",) if java else ("No listed programming language is suggested for this subjective question.",)),
                source_label=field.label,
                answer_policy=AnswerPolicy.TEXT_DRAFT_REVIEW,
                suggested_answer=java,
            ))
            continue

        if canonical in {CanonicalField.WORK_AUTHORIZATION, CanonicalField.LEGAL_DECLARATION}:
            explicit = facts.sponsorship_response if re.search(r"sponsor", field.label, re.I) else facts.work_authorization_response
            policy = AnswerPolicy.LEGAL
            suggestion = explicit
            mappings.append(FieldMapping(
                field_id=field.id,
                canonical_field=canonical,
                confidence=confidence,
                evidence=evidence + (("A manually configured answer is available and remains for human review.",) if explicit else ("No legal or work-authorization answer is inferred.",)),
                source_label=field.label,
                answer_policy=policy,
                suggested_answer=suggestion,
            ))
            continue

        if canonical is CanonicalField.OPTIONAL_SELF_IDENTIFICATION:
            policy = AnswerPolicy.OPTIONAL_SELF_IDENTIFICATION if _OPTIONAL_SELF_ID_RE.search(field.label) else AnswerPolicy.SENSITIVE
        elif canonical is CanonicalField.SALARY_EXPECTATION:
            policy = AnswerPolicy.SALARY_SUGGESTION_REVIEW
        elif canonical in {
            CanonicalField.CV,
            CanonicalField.COVER_LETTER,
            CanonicalField.PORTFOLIO_DOCUMENT,
            CanonicalField.OTHER_DOCUMENT,
        }:
            policy = AnswerPolicy.DOCUMENT_RECOMMENDATION_ONLY
        elif canonical is CanonicalField.CUSTOM_QUESTION:
            policy = AnswerPolicy.TEXT_DRAFT_REVIEW
        else:
            policy = AnswerPolicy.NEEDS_USER_INPUT

        suggestion = None
        recommendation = None
        if canonical is CanonicalField.SALARY_EXPECTATION and not _HISTORICAL_SALARY_RE.search(field.label):
            suggestion = _salary_suggestion(candidate)
        elif canonical in {
            CanonicalField.CV,
            CanonicalField.COVER_LETTER,
            CanonicalField.PORTFOLIO_DOCUMENT,
            CanonicalField.OTHER_DOCUMENT,
        }:
            recommendation = _document_recommendation(canonical, package=package, documents=documents)
        elif policy is AnswerPolicy.TEXT_DRAFT_REVIEW:
            question = ApplicationQuestion(
                id=field.id,
                label=field.label,
                required=field.required,
                options=field.options,
                source_field_name=str(field.dom_hint.get("name", "")) or None,
                normalized_type=_question_type(field),
                extracted_from="browser_form",
                confidence=1.0,
                evidence="Label and control metadata extracted from the visible form.",
                handling=ApplicationQuestionHandling.NEEDS_USER_INPUT,
            )
            drafted = draft_answers(
                [question],
                candidate=candidate,
                job_title=package.job_title,
                job_description=" ".join(item.text for item in package.requirements),
                projects=projects,
                writing_style=CandidateWritingStyle(),
            )[0]
            suggestion = str(drafted.answer) if drafted.answer is not None else None
        else:
            suggestion = None

        mappings.append(FieldMapping(
            field_id=field.id,
            canonical_field=canonical,
            confidence=confidence,
            evidence=evidence,
            source_label=field.label,
            answer_policy=policy,
            suggested_answer=suggestion,
            recommendation=recommendation,
        ))
    return tuple(mappings)


def safe_fill_plan(
    snapshot: ApplicationFormSnapshot,
    mappings: tuple[FieldMapping, ...],
    *,
    candidate: CandidateConfig,
    facts: CandidateApplicationFacts,
) -> dict[str, str]:
    """Return ephemeral values for factual, exact, currently-empty controls only."""

    fields = {field.id: field for field in snapshot.fields}
    plan: dict[str, str] = {}
    if snapshot.manual_intervention_required:
        return plan
    for mapping in mappings:
        field = fields.get(mapping.field_id)
        if (
            field is None
            or field.current_value_present
            or mapping.answer_policy is not AnswerPolicy.SAFE_AUTO_FILL
            or mapping.confidence is not MappingConfidence.HIGH
        ):
            continue
        if field.field_type is FormFieldType.RADIO and len(field.option_ordinals) != len(field.options):
            continue
        if mapping.canonical_field is CanonicalField.RELOCATION:
            value = _explicit_response(field, facts.relocation_response)
            if value is None:
                country = facts.current_country or candidate.profile.current_country
                value = next(
                    (option for option in field.options if _fold(option) == "i am in spain already"),
                    None,
                ) if country and country.casefold() == "spain" else None
        else:
            value = _configured_value(mapping.source_key, candidate, facts)
            if mapping.canonical_field in {
                CanonicalField.PREVIOUS_EMPLOYMENT,
                CanonicalField.CURRENTLY_IN_SPAIN,
                CanonicalField.REGION,
            }:
                value = _explicit_response(field, value)
        if value is None:
            continue
        if field.options:
            matching_option = next((option for option in field.options if option.casefold() == value.casefold()), None)
            if matching_option is None:
                continue
            value = matching_option
        plan[field.id] = value
    return plan
