"""Conservative extraction of public application form fields and job requirements."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

from ai_job_hunter.application_prep.models import (
    ApplicationQuestion,
    ApplicationQuestionHandling,
    ApplicationQuestionType,
    JobApplicationRequirement,
    RequirementCategory,
)


_QUESTION_CONTAINERS = {
    "greenhouse": ("questions", "location_questions", "compliance", "demographic_questions"),
    "ashby": ("applicationFormDefinition",),
}
_FIELD_CHILD_KEYS = {
    "fields",
    "questions",
    "location_questions",
    "demographic_questions",
    "compliance",
    "sections",
    "items",
    "applicationformdefinition",
    "formfields",
}
_LABEL_KEYS = ("label", "question", "prompt", "title", "name")
_TYPE_KEYS = ("type", "fieldType", "field_type", "questionType", "inputType", "input_type")
_ID_KEYS = ("id", "fieldId", "field_id", "key", "name")
_OPTION_KEYS = ("options", "choices", "values", "answer_options", "enum")


def extract_application_questions(
    raw_metadata: Mapping[str, Any] | None, *, provider: str
) -> list[ApplicationQuestion]:
    """Extract only fields found in known structured ATS form containers.

    Public job description prose is deliberately never inspected here. Unsupported
    or unknown provider structures produce no questions rather than guessed ones.
    """

    if not isinstance(raw_metadata, Mapping):
        return []
    provider_key = provider.strip().casefold()
    if provider_key in {"gh", "greenhouse", "greenhouse.io"}:
        provider_key = "greenhouse"
    elif provider_key in {"ashby", "ashbyhq"}:
        provider_key = "ashby"
    else:
        return []

    fields: list[tuple[Mapping[str, Any], str]] = []
    seen_locations: set[str] = set()
    for container_name in _QUESTION_CONTAINERS[provider_key]:
        if container_name not in raw_metadata:
            continue
        _collect_fields(
            raw_metadata[container_name],
            path=f"{provider_key}.{container_name}",
            output=fields,
            seen_locations=seen_locations,
            direct=provider_key == "greenhouse",
        )

    result: list[ApplicationQuestion] = []
    seen_ids: set[str] = set()
    for index, (field, source_path) in enumerate(fields):
        label = _first_text(field, _LABEL_KEYS)
        if not label:
            continue
        field_id = _first_identifier(field, _ID_KEYS)
        source_field_name = field_id[:255] if field_id else None
        normalized_type = _normalize_question_type(_first_value(field, _TYPE_KEYS), field)
        options = _extract_options(_first_value(field, _OPTION_KEYS))
        required_value = field.get("required", field.get("isRequired", field.get("is_required", False)))
        required = required_value is True or (
            isinstance(required_value, str) and required_value.strip().casefold() in {"true", "yes", "1"}
        )
        handling = _question_handling(label, normalized_type)
        identifier = _question_identifier(provider_key, source_path, field_id, label, index)
        if identifier in seen_ids:
            identifier = _question_identifier(provider_key, source_path, field_id, label, index, salt="duplicate")
        seen_ids.add(identifier)
        evidence = f"Structured {provider_key} form field at {source_path}: {label}"
        if field_id:
            evidence += f" (field id: {field_id})"
        result.append(
            ApplicationQuestion(
                id=identifier,
                label=label[:1000],
                required=required,
                options=options,
                source_field_name=source_field_name,
                normalized_type=normalized_type,
                extracted_from=f"{provider_key} application form",
                confidence=0.94 if normalized_type is not ApplicationQuestionType.UNKNOWN else 0.82,
                evidence=evidence[:2000],
                handling=handling,
            )
        )
    return result


def _collect_fields(
    node: Any,
    *,
    path: str,
    output: list[tuple[Mapping[str, Any], str]],
    seen_locations: set[str],
    direct: bool,
) -> None:
    if isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
        for index, item in enumerate(node):
            item_path = f"{path}[{index}]"
            if isinstance(item, Mapping) and _question_wrapper_has_fields(item):
                _collect_question_wrapper(
                    item,
                    path=item_path,
                    output=output,
                    seen_locations=seen_locations,
                )
                continue
            if isinstance(item, Mapping) and _looks_like_field(item, allow_label_only=direct):
                if item_path not in seen_locations:
                    output.append((item, item_path))
                    seen_locations.add(item_path)
            else:
                _collect_fields(
                    item,
                    path=item_path,
                    output=output,
                    seen_locations=seen_locations,
                    direct=False,
                )
        return
    if not isinstance(node, Mapping):
        return
    if _question_wrapper_has_fields(node):
        _collect_question_wrapper(node, path=path, output=output, seen_locations=seen_locations)
        return
    if _looks_like_field(node, allow_label_only=direct):
        if path not in seen_locations:
            output.append((node, path))
            seen_locations.add(path)
        return
    for key, value in node.items():
        if str(key).casefold() in _FIELD_CHILD_KEYS:
            _collect_fields(
                value,
                path=f"{path}.{key}",
                output=output,
                seen_locations=seen_locations,
                direct=str(key).casefold() in {"fields", "questions", "location_questions", "demographic_questions"},
            )


def _question_wrapper_has_fields(node: Mapping[str, Any]) -> bool:
    has_label = bool(_first_text(node, ("label", "question", "prompt")))
    fields = _first_value(node, ("fields", "formFields", "form_fields"))
    return has_label and isinstance(fields, Sequence) and not isinstance(fields, (str, bytes, bytearray))


def _collect_question_wrapper(
    wrapper: Mapping[str, Any],
    *,
    path: str,
    output: list[tuple[Mapping[str, Any], str]],
    seen_locations: set[str],
) -> None:
    label = _first_text(wrapper, ("label", "question", "prompt"))
    fields = _first_value(wrapper, ("fields", "formFields", "form_fields"))
    if not label or not isinstance(fields, Sequence) or isinstance(fields, (str, bytes, bytearray)):
        return
    for index, field in enumerate(fields):
        field_path = f"{path}.fields[{index}]"
        if not isinstance(field, Mapping):
            continue
        flattened = dict(field)
        # Greenhouse's public form shape puts the human question label and
        # required flag on the parent, while field name/type/options live below.
        flattened["label"] = label
        for required_key in ("required", "isRequired", "is_required"):
            if required_key in wrapper and not any(key in flattened for key in ("required", "isRequired", "is_required")):
                flattened[required_key] = wrapper[required_key]
                break
        if field_path not in seen_locations:
            output.append((flattened, field_path))
            seen_locations.add(field_path)


def _looks_like_field(field: Mapping[str, Any], *, allow_label_only: bool) -> bool:
    if not _first_text(field, _LABEL_KEYS):
        return False
    if allow_label_only:
        return True
    indicators = (*_TYPE_KEYS, *_ID_KEYS, *_OPTION_KEYS, "required", "isRequired", "is_required")
    return any(key in field for key in indicators)


def _first_value(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    lowered = {str(key).casefold(): value for key, value in mapping.items()}
    for key in keys:
        if key.casefold() in lowered:
            return lowered[key.casefold()]
    return None


def _first_text(mapping: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    value = _first_value(mapping, keys)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _first_identifier(mapping: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    value = _first_value(mapping, keys)
    if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip():
        return str(value).strip()
    return None


def _normalize_question_type(value: Any, field: Mapping[str, Any]) -> ApplicationQuestionType:
    if not isinstance(value, str):
        return ApplicationQuestionType.UNKNOWN
    normalized = re.sub(r"[^a-z0-9]+", "", value.casefold())
    aliases = {
        "text": ApplicationQuestionType.TEXT,
        "shorttext": ApplicationQuestionType.TEXT,
        "input": ApplicationQuestionType.TEXT,
        "inputtext": ApplicationQuestionType.TEXT,
        "string": ApplicationQuestionType.TEXT,
        "textarea": ApplicationQuestionType.TEXTAREA,
        "longtext": ApplicationQuestionType.TEXTAREA,
        "paragraph": ApplicationQuestionType.TEXTAREA,
        "yesno": ApplicationQuestionType.YES_NO,
        "boolean": ApplicationQuestionType.YES_NO,
        "bool": ApplicationQuestionType.YES_NO,
        "checkbox": ApplicationQuestionType.YES_NO,
        "number": ApplicationQuestionType.NUMBER,
        "numeric": ApplicationQuestionType.NUMBER,
        "select": ApplicationQuestionType.SELECT,
        "inputselect": ApplicationQuestionType.SELECT,
        "dropdown": ApplicationQuestionType.SELECT,
        "singleselect": ApplicationQuestionType.SELECT,
        "radiobutton": ApplicationQuestionType.SELECT,
        "radio": ApplicationQuestionType.SELECT,
        "multiselect": ApplicationQuestionType.MULTISELECT,
        "multipleselect": ApplicationQuestionType.MULTISELECT,
        "multivaluemultiselect": ApplicationQuestionType.MULTISELECT,
        "url": ApplicationQuestionType.URL,
        "email": ApplicationQuestionType.EMAIL,
        "phone": ApplicationQuestionType.PHONE,
        "date": ApplicationQuestionType.DATE,
        "file": ApplicationQuestionType.FILE,
        "inputfile": ApplicationQuestionType.FILE,
        "attachment": ApplicationQuestionType.FILE,
        "inputmultiselect": ApplicationQuestionType.MULTISELECT,
    }
    if normalized in {"multivaluesingleselect", "multivaluesinglechoice"}:
        return ApplicationQuestionType.SELECT
    mapped = aliases.get(normalized)
    if mapped is ApplicationQuestionType.YES_NO and _extract_options(_first_value(field, _OPTION_KEYS)):
        return ApplicationQuestionType.SELECT
    return mapped or ApplicationQuestionType.UNKNOWN


def _extract_options(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    result: list[str] = []
    for option in value:
        if isinstance(option, str):
            text = option.strip()
        elif isinstance(option, Mapping):
            text = _first_text(option, ("label", "name", "value", "title")) or ""
        else:
            text = ""
        if text and text not in result:
            result.append(text[:255])
    return tuple(result)


def _question_handling(label: str, question_type: ApplicationQuestionType) -> ApplicationQuestionHandling:
    normalized = label.casefold()
    legal_terms = (
        "work authorization",
        "authorized to work",
        "eligible to work",
        "visa",
        "sponsorship",
        "criminal conviction",
        "background check",
        "agree to",
        "consent",
        "certify",
        "certification",
        "terms and conditions",
        "privacy notice",
        "legally",
    )
    sensitive_terms = (
        "gender",
        "race",
        "ethnic",
        "disability",
        "veteran",
        "sexual orientation",
        "gender identity",
        "date of birth",
        "religion",
        "demographic",
        "pronoun",
        "marital status",
    )
    if any(term in normalized for term in legal_terms):
        return ApplicationQuestionHandling.LEGAL
    if any(term in normalized for term in sensitive_terms):
        return ApplicationQuestionHandling.SENSITIVE
    if question_type is ApplicationQuestionType.UNKNOWN:
        return ApplicationQuestionHandling.UNSUPPORTED
    return ApplicationQuestionHandling.NEEDS_USER_INPUT


def _question_identifier(
    provider: str, path: str, field_id: str | None, label: str, index: int, *, salt: str = ""
) -> str:
    source = "|".join((provider, path, field_id or "", label, str(index), salt))
    return f"question-{hashlib.sha256(source.encode('utf-8')).hexdigest()[:32]}"


def extract_job_requirements(
    description: str | None, *, extracted_from: str = "public job posting"
) -> list[JobApplicationRequirement]:
    """Split job-posting text into evidence-backed clauses with cautious categories."""

    if not isinstance(description, str) or not description.strip():
        return []
    requirements: list[JobApplicationRequirement] = []
    section = RequirementCategory.UNKNOWN
    ordinal = 0
    for line_number, raw_line in enumerate(description.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        heading, remainder = _section_heading(line)
        if heading is not None:
            section = heading
            line = remainder
            if not line:
                continue
        for clause in _split_clauses(line):
            text = clause.strip().lstrip("•*-–— ").strip()
            if not text:
                continue
            category, cue = _classify_requirement(text, section)
            ordinal += 1
            digest = hashlib.sha256(f"{line_number}|{ordinal}|{text}".encode("utf-8")).hexdigest()[:32]
            evidence = f"{extracted_from}, line {line_number}: {text}"
            confidence = 0.88 if cue == "explicit" else 0.76 if cue == "section" else 0.48
            requirements.append(
                JobApplicationRequirement(
                    id=f"requirement-{digest}",
                    text=text[:2000],
                    category=category,
                    extracted_from=extracted_from[:100],
                    evidence=evidence[:2000],
                    confidence=confidence,
                )
            )
    return requirements


def _section_heading(line: str) -> tuple[RequirementCategory | None, str]:
    normalized = re.sub(r"[^a-z0-9 ]", "", line.casefold()).strip()
    if normalized in {"this role requires", "what this role requires"}:
        return RequirementCategory.MUST_HAVE, ""
    headings: tuple[tuple[RequirementCategory, tuple[str, ...]], ...] = (
        (RequirementCategory.MUST_HAVE, ("requirements", "minimum requirements", "qualifications", "required qualifications", "minimum qualifications", "basic qualifications", "what youll need", "what you need", "what were looking for", "what youll bring", "your qualifications")),
        (RequirementCategory.PREFERRED, ("preferred qualifications", "preferred experience", "nice to have", "bonus points", "bonus points if you have", "bonus points if you bring", "desired qualifications", "additional qualifications")),
        (RequirementCategory.RESPONSIBILITY, ("responsibilities", "what youll do", "what you will do", "your responsibilities", "role responsibilities")),
        (RequirementCategory.BENEFIT, ("benefits", "perks", "what we offer", "compensation and benefits")),
    )
    for category, labels in headings:
        for label in labels:
            if normalized == label:
                return category, ""
            prefix = label + " "
            if normalized.startswith(prefix) and ":" in line:
                colon_index = line.find(":")
                return category, line[colon_index + 1 :].strip()
    if normalized in {
        "your opportunity",
        "our hiring process",
        "about us",
        "about the company",
        "about the role",
        "about you",
    }:
        return RequirementCategory.UNKNOWN, ""
    return None, line


def _split_clauses(line: str) -> list[str]:
    # Keep bullets/lines as the primary units and split only sentence boundaries.
    return [part for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9•*])", line) if part.strip()]


def _classify_requirement(text: str, section: RequirementCategory) -> tuple[RequirementCategory, str]:
    normalized = text.casefold()
    preferred_cues = (
        r"\bpreferred\s+(?:qualification|experience|skill|background|requirement)s?\b",
        r"\b(?:experience|skill|background|qualification)\b.{0,80}\bis preferred\b",
        r"\bnice to have\b",
        r"\bwould be a plus\b",
        r"\bis a plus\b",
        r"\bbonus points\b",
        r"\bbonus if\b",
        r"\bideally\b",
        r"\bdesirable\b",
    )
    if any(re.search(cue, normalized) for cue in preferred_cues):
        return RequirementCategory.PREFERRED, "explicit"

    benefit_cues = (
        "benefits include",
        "health insurance",
        "medical insurance",
        "paid time off",
        "parental leave",
        "401k",
        "401(k)",
        "equity package",
        "annual bonus",
        "salary range",
        "compensation package",
        "flexible vacation",
        "wellness benefit",
    )
    if any(cue in normalized for cue in benefit_cues):
        return RequirementCategory.BENEFIT, "explicit"

    administrative_or_legal_disclosures = (
        "reasonable accommodation",
        "application or recruiting process",
        "employment eligibility verification",
        "all persons hired",
        "required to verify identity",
        "background check is required to join",
        "export compliance assessment",
    )
    if any(cue in normalized for cue in administrative_or_legal_disclosures):
        return RequirementCategory.UNKNOWN, "unknown"

    must_cues = (
        r"\bmust\b",
        r"\brequired\b",
        r"\brequires?\b",
        r"\bminimum of\b",
        r"\bat least\b",
        r"\bmandatory\b",
        r"\b[0-9]+\s*\+?\s*years? of (?:relevant )?experience\b",
        r"\b[0-9]+\s*\+\s*years?\b",
    )
    if any(re.search(cue, normalized) for cue in must_cues):
        return RequirementCategory.MUST_HAVE, "explicit"

    if section is RequirementCategory.PREFERRED:
        return (
            (RequirementCategory.PREFERRED, "section")
            if _looks_like_qualification(text)
            else (RequirementCategory.UNKNOWN, "unknown")
        )
    if section is RequirementCategory.BENEFIT:
        return RequirementCategory.BENEFIT, "section"
    if section is RequirementCategory.RESPONSIBILITY:
        if _looks_like_responsibility(text):
            return RequirementCategory.RESPONSIBILITY, "section"
        return RequirementCategory.UNKNOWN, "unknown"
    if section is RequirementCategory.MUST_HAVE and _looks_like_qualification(text):
        return RequirementCategory.MUST_HAVE, "section"
    if _looks_like_responsibility(text):
        return RequirementCategory.RESPONSIBILITY, "explicit"
    return RequirementCategory.UNKNOWN, "unknown"


def _looks_like_qualification(text: str) -> bool:
    normalized = text.casefold().lstrip("•*-–— ")
    return bool(
        re.search(
            r"\b(experience|proficiency|proficient|knowledge|degree|bachelor|master|phd|skills?|ability|able to|fluent|certification|years?|contributions?|understanding|comfort|collaborative|adaptability|curiosity|familiarity)\b",
            normalized,
        )
    )


def _looks_like_responsibility(text: str) -> bool:
    normalized = text.casefold().lstrip("•*-–— ")
    if re.search(r"\b(you will|responsible for|own and|lead|collaborate|partner with|build|design|develop|maintain|implement|deliver|drive|manage|create|support|improve|coordinate|analyze|analyse)\b", normalized):
        return True
    if re.match(r"^(?:build|design|develop|maintain|implement|deliver|lead|manage|create|support|improve|coordinate|analyze|analyse|collaborate|partner)\b", normalized):
        return True
    return bool(re.match(r"^work with .+\b(?:to|on|by)\b", normalized))
