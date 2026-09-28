"""Extract a small, redacted form description from HTML or DOM records."""

from __future__ import annotations

from html.parser import HTMLParser
import re
from typing import Any, Mapping, Sequence

from ai_job_hunter.application_prep.browser.models import (
    ApplicationFormSnapshot,
    ATSProvider,
    FormField,
    FormFieldType,
    ManualInterventionReason,
)
from ai_job_hunter.application_prep.browser.safety import (
    detect_ats,
    make_form_action,
)


_STEP_RE = re.compile(r"\bstep\s+(\d+)\s+(?:of|/)\s+(\d+)\b", re.I)
_LOGIN_RE = re.compile(
    r"\b(?:sign in|log in|login|sign[ -]?up|register|registration|create (?:an? )?(?:account|profile)|email verification|verify your email|"
    r"continue with google|sign in with google|google sign in|oauth|two.factor|multi.factor|"
    r"verification code|one.time code|security code|authenticator)\b",
    re.I,
)
_CAPTCHA_RE = re.compile(r"(?:captcha|recaptcha|hcaptcha|challenge-platform)", re.I)


def _field_type(tag: str, value: str = "") -> FormFieldType:
    value = value.casefold()
    if tag == "textarea":
        return FormFieldType.TEXTAREA
    if tag == "select":
        return FormFieldType.MULTISELECT if value == "multiple" else FormFieldType.SELECT
    return {
        "text": FormFieldType.TEXT,
        "search": FormFieldType.TEXT,
        "email": FormFieldType.EMAIL,
        "tel": FormFieldType.PHONE,
        "url": FormFieldType.URL,
        "number": FormFieldType.NUMBER,
        "date": FormFieldType.DATE,
        "checkbox": FormFieldType.CHECKBOX,
        "radio": FormFieldType.RADIO,
        "file": FormFieldType.FILE,
    }.get(value, FormFieldType.OTHER)


def _normalise_record(record: Mapping[str, Any], index: int) -> FormField | None:
    tag = str(record.get("tag", "input")).casefold()
    input_type = str(record.get("type", "text")).casefold()
    if tag not in {"input", "select", "textarea"} or input_type in {
        "hidden", "submit", "image", "button", "reset"
    }:
        return None
    if record.get("visible") is False:
        return None
    label = " ".join(str(record.get("label") or "").split())
    dom_hint = record.get("dom_hint") or {}
    if not label:
        label = " ".join(str(dom_hint.get(key, "")) for key in ("aria_label", "placeholder", "name", "id")).strip()
    if not label:
        label = f"Unlabelled field {index + 1}"
    identity = str(record.get("id") or dom_hint.get("id") or record.get("name") or dom_hint.get("name") or f"field-{index + 1}")
    options = tuple(
        " ".join(str(option).split())[:300]
        for option in (record.get("options") or ())
        if str(option).strip()
    )
    return FormField(
        id=identity[:255],
        label=label[:1000],
        label_source=str(record.get("label_source") or "label")[:40],
        field_type=_field_type(tag, input_type),
        required=bool(record.get("required")),
        options=options,
        current_value_present=bool(record.get("current_value_present")),
        dom_hint={
            key: value
            for key, value in {
                "id": dom_hint.get("id", ""),
                "name": dom_hint.get("name", ""),
                "type": input_type,
                "ordinal": int(record.get("ordinal", index)),
            }.items()
            if value != ""
        },
    )


def snapshot_from_dom_records(
    *,
    url: str,
    records: Sequence[Mapping[str, Any]],
    actions: Sequence[Mapping[str, Any]] = (),
    page_text: str = "",
    captcha_detected: bool = False,
    captcha_text_detected: bool = False,
    login_detected: bool = False,
    extracted_at=None,
) -> ApplicationFormSnapshot:
    """Create a persisted snapshot without retaining entered field values or HTML."""

    ats = detect_ats(url)
    records = _group_radio_records(records)
    fields = tuple(
        field
        for index, record in enumerate(records)
        if (field := _normalise_record(record, index)) is not None
    )
    form_actions = []
    for action_index, action in enumerate(actions):
        item = make_form_action(
            str(action.get("label") or ""),
            str(action.get("control_type") or "button"),
        )
        if item is not None:
            click_ordinal = action.get("click_ordinal")
            form_actions.append(item.model_copy(update={
                "ordinal": int(action.get("ordinal", action_index)),
                "click_ordinal": int(click_ordinal) if click_ordinal is not None else None,
            }))
    step_match = _STEP_RE.search(page_text)
    step = int(step_match.group(1)) if step_match else None
    step_count = int(step_match.group(2)) if step_match else None
    has_password = any(
        str(record.get("type", "")).casefold() == "password" and record.get("visible") is not False
        for record in records
    )
    if captcha_detected or captcha_text_detected or _CAPTCHA_RE.search(page_text):
        manual_reason = ManualInterventionReason.CAPTCHA
    elif login_detected or has_password or _LOGIN_RE.search(page_text):
        manual_reason = ManualInterventionReason.AUTHENTICATION
    elif ats is ATSProvider.UNKNOWN:
        manual_reason = ManualInterventionReason.UNKNOWN_ATS
    elif not fields:
        manual_reason = ManualInterventionReason.NO_VISIBLE_FORM
    else:
        manual_reason = None
    kwargs = {"extracted_at": extracted_at} if extracted_at is not None else {}
    return ApplicationFormSnapshot(
        url=url,
        ats=ats,
        step=step,
        step_count=step_count,
        fields=fields,
        actions=tuple(form_actions),
        manual_intervention_required=manual_reason is not None,
        manual_intervention_reason=manual_reason,
        **kwargs,
    )


class _FixtureParser(HTMLParser):
    """Minimal HTML fixture parser; captures field metadata, never field text values."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records: list[dict[str, Any]] = []
        self.actions: list[dict[str, str]] = []
        self.labels: dict[str, list[str]] = {}
        self._label_stack: list[tuple[str | None, list[str], int]] = []
        self._action_stack: list[dict[str, str]] = []
        self._option_stack: list[dict[str, Any]] = []
        self._select_stack: list[dict[str, Any]] = []
        self._textarea_stack: list[dict[str, Any]] = []
        self._fieldset_labels: list[str] = []
        self._legend_parts: list[str] | None = None
        self.text: list[str] = []
        self.captcha_detected = False
        self.button_action_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.casefold(): value or "" for key, value in attrs}
        if _CAPTCHA_RE.search(" ".join(f"{key}={value}" for key, value in attributes.items())):
            self.captcha_detected = True
        if tag == "label":
            self._label_stack.append((attributes.get("for") or None, [], len(self.records)))
        if tag == "fieldset":
            self._fieldset_labels.append("")
        if tag == "legend":
            self._legend_parts = []
        if tag == "input":
            input_type = attributes.get("type", "text").casefold()
            if input_type in {"submit", "image"}:
                if self._is_visible_control(attributes):
                    label = attributes.get("value") or attributes.get("alt") or attributes.get("aria-label")
                    self.actions.append({
                        "label": label or ("Image submit control" if input_type == "image" else "Submit control"),
                        "control_type": "submit",
                        "ordinal": str(len(self.actions)),
                    })
            else:
                record = self._make_input(attributes)
                if record:
                    self.records.append(record)
        elif tag == "select":
            record = self._make_input(attributes, tag="select")
            if record:
                record["options"] = []
                self.records.append(record)
                self._select_stack.append(record)
        elif tag == "option" and self._select_stack:
            self._option_stack.append({"text": [], "selected": "selected" in attributes})
        elif tag == "textarea":
            record = self._make_input(attributes, tag="textarea")
            if record:
                record["current_value_present"] = False
                self.records.append(record)
                self._textarea_stack.append(record)
        elif tag == "button" or attributes.get("role") == "button":
            self._action_stack.append({
                "tag": tag,
                "label": "",
                "control_type": "submit" if attributes.get("type", "").casefold() in {"", "submit"} else tag,
                "ordinal": str(len(self.actions)),
                "click_ordinal": str(self.button_action_count),
            })
            self.button_action_count += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.text.append(data)
        if self._label_stack:
            self._label_stack[-1][1].append(data)
        if self._legend_parts is not None:
            self._legend_parts.append(data)
        if self._action_stack:
            self._action_stack[-1]["label"] += data
        if self._option_stack:
            self._option_stack[-1]["text"].append(data)
        if self._textarea_stack and data.strip():
            self._textarea_stack[-1]["current_value_present"] = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "label" and self._label_stack:
            target, parts, start_index = self._label_stack.pop()
            label = " ".join("".join(parts).split())
            if target and label:
                self.labels.setdefault(target, []).append(label)
            elif label:
                for record in self.records[start_index:]:
                    if not record.get("wrapped_label"):
                        record["wrapped_label"] = label
        elif tag == "legend" and self._legend_parts is not None:
            label = " ".join("".join(self._legend_parts).split())
            if self._fieldset_labels:
                self._fieldset_labels[-1] = label
            self._legend_parts = None
        elif tag == "fieldset" and self._fieldset_labels:
            self._fieldset_labels.pop()
        elif tag == "option" and self._option_stack:
            option = self._option_stack.pop()
            if self._select_stack:
                label = " ".join("".join(option["text"]).split())
                if label:
                    self._select_stack[-1]["options"].append(label)
                if option["selected"]:
                    self._select_stack[-1]["current_value_present"] = True
        elif tag == "select" and self._select_stack:
            self._select_stack.pop()
        elif tag == "textarea" and self._textarea_stack:
            self._textarea_stack.pop()
        elif self._action_stack and self._action_stack[-1]["tag"] == tag:
            if self._action_stack:
                action = self._action_stack.pop()
                if action["label"].strip():
                    self.actions.append(action)

    @staticmethod
    def _is_visible_control(attributes: dict[str, str]) -> bool:
        if "hidden" in attributes or "disabled" in attributes:
            return False
        style = attributes.get("style", "").replace(" ", "").casefold()
        return "display:none" not in style and "visibility:hidden" not in style

    def _make_input(self, attributes: dict[str, str], *, tag: str = "input") -> dict[str, Any] | None:
        input_type = attributes.get("type", "text").casefold()
        if input_type == "hidden" or "hidden" in attributes or "disabled" in attributes:
            return None
        style = attributes.get("style", "").replace(" ", "").casefold()
        if "display:none" in style or "visibility:hidden" in style:
            return None
        identity = attributes.get("id") or attributes.get("name") or f"field-{len(self.records) + 1}"
        label = attributes.get("aria-label") or attributes.get("placeholder") or ""
        label_source = "aria" if attributes.get("aria-label") else "placeholder" if attributes.get("placeholder") else "attribute"
        record: dict[str, Any] = {
            "tag": tag,
            "type": input_type,
            "id": identity,
            "name": attributes.get("name", ""),
            "label": label,
            "label_source": label_source,
            "group_label": self._fieldset_labels[-1] if self._fieldset_labels else "",
            "option_label": "",
            "label_target": attributes.get("id") or attributes.get("name") or "",
            "required": "required" in attributes or attributes.get("aria-required", "").casefold() == "true",
            "current_value_present": (
                "checked" in attributes
                if input_type in {"checkbox", "radio"}
                else bool(attributes.get("value", "").strip())
            ),
            "visible": True,
            "dom_hint": {
                "id": attributes.get("id", ""),
                "name": attributes.get("name", ""),
                "type": input_type,
            },
            "ordinal": len(self.records),
        }
        if tag == "select" and "multiple" in attributes:
            record["type"] = "multiple"
        return record


def extract_snapshot_from_html(
    html: str,
    *,
    url: str,
    extracted_at=None,
) -> ApplicationFormSnapshot:
    """Offline fixture entry point. HTML is consumed in memory and never retained."""

    parser = _FixtureParser()
    parser.feed(html)
    for record in parser.records:
        if record.get("label"):
            continue
        record_id = record.get("id", "")
        record_name = record.get("name", "")
        candidates = parser.labels.get(record_id) or parser.labels.get(record_name) or []
        own_label = candidates[0] if candidates else record.get("wrapped_label", "")
        record["option_label"] = own_label if record.get("type") == "radio" else ""
        record["label"] = record.get("group_label") or own_label
        if candidates or record.get("wrapped_label"):
            record["label_source"] = "label"
        record["dom_hint"] = {
            key: value for key, value in record.get("dom_hint", {}).items()
            if key in {"id", "name", "type"} and value
        }
    snapshot = snapshot_from_dom_records(
        url=url,
        records=parser.records,
        actions=parser.actions,
        page_text=" ".join(parser.text),
        captcha_detected=parser.captcha_detected,
        captcha_text_detected=bool(_CAPTCHA_RE.search(" ".join(parser.text))),
        extracted_at=extracted_at,
    )
    return snapshot


def _group_radio_records(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Represent a same-name radio group once and retain only option labels."""

    result: list[Mapping[str, Any]] = []
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for index, record in enumerate(records):
        if str(record.get("type", "")).casefold() != "radio":
            result.append(record)
            continue
        dom_hint = record.get("dom_hint") or {}
        name = str(record.get("name") or dom_hint.get("name") or record.get("id") or index)
        group_label = str(record.get("group_label") or record.get("label") or "").strip()
        key = (name, group_label)
        if key not in groups:
            groups[key] = {
                "tag": "input",
                "type": "radio",
                "id": f"radio:{name}:{len(groups) + 1}",
                "name": name,
                "label": group_label,
                "label_source": record.get("label_source", "label"),
                "required": bool(record.get("required")),
                "options": [],
                "current_value_present": bool(record.get("current_value_present")),
                "visible": record.get("visible", True),
                "ordinal": int(record.get("ordinal", index)),
                "dom_hint": {"id": str(dom_hint.get("id", "")), "name": name, "type": "radio", "ordinal": int(record.get("ordinal", index))},
            }
            result.append(groups[key])
        group = groups[key]
        option_label = str(record.get("option_label") or "").strip()
        if option_label and option_label not in group["options"]:
            group["options"].append(option_label)
        group["required"] = group["required"] or bool(record.get("required"))
        group["current_value_present"] = group["current_value_present"] or bool(record.get("current_value_present"))
    return result
