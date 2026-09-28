"""Explicit, optional Playwright runner with no submission or upload API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ai_job_hunter.application_prep.browser.extraction import snapshot_from_dom_records
from ai_job_hunter.application_prep.browser.models import (
    ApplicationFormSnapshot,
    ATSProvider,
    FieldMapping,
    FormFieldType,
    ManualInterventionReason,
)
from ai_job_hunter.application_prep.browser.safety import (
    BrowserSafetyError,
    NetworkDecision,
    SUBMIT_GUARD_INIT_SCRIPT,
    assert_safe_next_action,
    network_decision,
    validate_application_url,
)


_DOM_INSPECT_SCRIPT = r"""
() => {
  const visible = el => {
    const style = getComputedStyle(el);
    const box = el.getBoundingClientRect();
    return !el.disabled && style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0;
  };
  const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  const fields = Array.from(document.querySelectorAll('input, select, textarea')).map((el, ordinal) => {
    const labelText = el.labels ? Array.from(el.labels).map(text).filter(Boolean).join(' ') : '';
    const labelledBy = (el.getAttribute('aria-labelledby') || '').split(/\s+/)
      .map(id => document.getElementById(id)).filter(Boolean).map(text).filter(Boolean).join(' ');
    const aria = el.getAttribute('aria-label') || '';
    const placeholder = el.getAttribute('placeholder') || '';
    const groupLabel = el.closest('fieldset')?.querySelector('legend');
    const groupText = groupLabel ? text(groupLabel) : '';
    const ownLabel = labelText || labelledBy || aria || placeholder || '';
    const label = groupText || ownLabel;
    const labelSource = labelText || labelledBy || groupText ? 'label' : aria ? 'aria' : placeholder ? 'placeholder' : 'attribute';
    const type = el.tagName === 'SELECT' ? (el.multiple ? 'multiple' : 'select') : el.tagName === 'TEXTAREA' ? 'textarea' : (el.type || 'text');
    const current = el.type === 'checkbox' || el.type === 'radio' ? !!el.checked : el.value !== undefined && String(el.value).length > 0;
    return {
      tag: el.tagName.toLowerCase(), type, id: el.id || el.name || `field-${ordinal + 1}`,
      name: el.name || '', label, group_label: groupText,
      option_label: el.type === 'radio' ? ownLabel : '', label_source: labelSource, visible: visible(el),
      required: !!el.required || el.getAttribute('aria-required') === 'true',
      current_value_present: current,
      options: el.tagName === 'SELECT' ? Array.from(el.options).map(option => text(option)).filter(Boolean) : [],
      ordinal, dom_hint: { id: el.id || '', name: el.name || '', type }
    };
  });
  const clickControls = Array.from(document.querySelectorAll('button, [role="button"]'));
  const actions = Array.from(document.querySelectorAll('button, [role="button"], input[type="submit"], input[type="image"]'))
    .map((el, ordinal) => {
      const inputControl = el.tagName === 'INPUT';
      const label = inputControl
        ? (el.value || el.alt || el.getAttribute('aria-label') || '')
        : text(el);
      return {
        label: label || (el.type === 'image' ? 'Image submit control' : 'Submit control'),
        control_type: inputControl ? 'submit' : el.tagName === 'BUTTON' ? (el.type || 'submit') : 'button-role',
        ordinal,
        click_ordinal: inputControl ? null : clickControls.indexOf(el),
        visible: visible(el)
      };
    }).filter(action => action.visible && action.label);
  const body = document.body ? document.body.innerText || '' : '';
  const stepMatch = body.match(/\bstep\s+\d+\s+(?:of|\/)\s+\d+\b/i);
  return {
    fields, actions,
    step_text: stepMatch ? stepMatch[0] : '',
    captcha_detected: !!document.querySelector('[id*="captcha" i], [class*="captcha" i], iframe[src*="captcha" i], iframe[src*="recaptcha" i]'),
    captcha_text_detected: /captcha|recaptcha|hcaptcha|human verification|verify that you are human/i.test(body),
    login_detected: /\b(?:sign in|log in|login|sign[ -]?up|register|registration|create (?:an? )?(?:account|profile)|email verification|verify your email|continue with google|sign in with google|google sign in|oauth|two.factor|multi.factor|verification code|one.time code|security code|authenticator)\b/i.test(body)
  };
}
"""

def _form_signature(page_url: str, raw: dict) -> tuple:
    """A value-free signature used to verify that an allowed Next changed the form."""

    fields = tuple(
        (
            str(field.get("label", "")),
            str(field.get("type", "")),
            bool(field.get("required")),
            tuple(field.get("options", ())),
            bool(field.get("current_value_present")),
        )
        for field in raw.get("fields", ()) if field.get("visible") is not False
    )
    actions = tuple(
        (str(item.get("label", "")), str(item.get("control_type", "")))
        for item in raw.get("actions", ()) if item.get("visible") is not False
    )
    return page_url, str(raw.get("step_text", "")), fields, actions


@dataclass(frozen=True, slots=True)
class MappingAndFillPlan:
    mappings: tuple[FieldMapping, ...]
    values_by_field_id: dict[str, str]


@dataclass(frozen=True, slots=True)
class BrowserRunResult:
    snapshots: tuple[ApplicationFormSnapshot, ...]
    mappings: tuple[FieldMapping, ...]
    filled_safe_field_ids: tuple[str, ...]
    advanced_steps: int
    manual_intervention_reason: ManualInterventionReason | None = None

    @property
    def final_snapshot(self) -> ApplicationFormSnapshot:
        return self.snapshots[-1]


class PlaywrightAssistedBrowser:
    """One-shot browser session; no browser Page or generic actions escape this class."""

    def inspect_and_fill(
        self,
        url: str,
        *,
        expected_ats: ATSProvider,
        plan_for_snapshot: Callable[[ApplicationFormSnapshot, str], MappingAndFillPlan],
        fill_safe: bool,
        max_steps: int = 5,
    ) -> BrowserRunResult:
        provider = validate_application_url(url, expected_ats)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise BrowserSafetyError(
                "Browser-assisted apply needs the optional Playwright dependency and Chromium installation."
            ) from error

        try:
            return self._run(
                sync_playwright,
                url=url,
                provider=provider,
                plan_for_snapshot=plan_for_snapshot,
                fill_safe=fill_safe,
                max_steps=max_steps,
            )
        except BrowserSafetyError:
            raise
        except Exception as error:
            # Exception text can contain URLs, form values, or browser payloads.
            raise BrowserSafetyError(
                f"Browser inspection stopped safely ({type(error).__name__}). No form data was logged."
            ) from None

    def _run(self, sync_playwright, *, url, provider, plan_for_snapshot, fill_safe, max_steps):
        snapshots: list[ApplicationFormSnapshot] = []
        mappings: list[FieldMapping] = []
        filled_ids: list[str] = []
        interacted = False
        manual_reason: ManualInterventionReason | None = None
        previous_signature: tuple | None = None
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            context = browser.new_context(
                service_workers="block",
                accept_downloads=False,
                permissions=[],
            )
            context.add_init_script(SUBMIT_GUARD_INIT_SCRIPT)

            def guard_route(route):
                request = route.request
                decision = network_decision(
                    url=request.url,
                    method=request.method,
                    resource_type=request.resource_type,
                    is_navigation=request.is_navigation_request(),
                    initial_url=url,
                    interacted_with_page=interacted,
                )
                if decision is NetworkDecision.ALLOW:
                    route.continue_()
                else:
                    route.abort("blockedbyclient")

            context.route("**/*", guard_route)
            if hasattr(context, "route_web_socket"):
                context.route_web_socket("**/*", lambda socket: socket.close())
            page = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                try:
                    page.wait_for_load_state("load", timeout=5000)
                except Exception:
                    pass
                for step_number in range(1, max(1, min(max_steps, 5)) + 1):
                    page_url = page.url
                    if validate_application_url(page_url) is not provider:
                        manual_reason = ManualInterventionReason.UNSUPPORTED_REDIRECT
                        break
                    raw = page.evaluate(_DOM_INSPECT_SCRIPT)
                    signature = _form_signature(page_url, raw)
                    if previous_signature is not None:
                        if signature == previous_signature:
                            break
                        previous_signature = None
                    snapshot = snapshot_from_dom_records(
                        url=page_url,
                        records=raw.get("fields", ()),
                        actions=raw.get("actions", ()),
                        page_text=str(raw.get("step_text", "")),
                        captcha_detected=bool(raw.get("captcha_detected")),
                        captcha_text_detected=bool(raw.get("captcha_text_detected")),
                        login_detected=bool(raw.get("login_detected")),
                    )
                    snapshot = snapshot.model_copy(update={
                        "fields": tuple(
                            field.model_copy(update={"id": f"step-{step_number}:{field.id}"})
                            for field in snapshot.fields
                        ),
                    })
                    snapshots.append(snapshot)
                    if snapshot.manual_intervention_required:
                        manual_reason = snapshot.manual_intervention_reason
                        break
                    plan = plan_for_snapshot(snapshot, page_url)
                    mappings.extend(plan.mappings)
                    if fill_safe:
                        filled_in_step: set[str] = set()
                        fields_by_id = {field.id: field for field in snapshot.fields}
                        for field_id, value in plan.values_by_field_id.items():
                            field = fields_by_id.get(field_id)
                            if field is None or field.current_value_present:
                                continue
                            ordinal = int(field.dom_hint.get("ordinal", -1))
                            if ordinal < 0:
                                continue
                            locator = page.locator("input, select, textarea").nth(ordinal)
                            if not locator.is_visible():
                                continue
                            if not locator.is_editable():
                                continue
                            interacted = True
                            if field.field_type is FormFieldType.SELECT:
                                locator.select_option(label=value, timeout=3000)
                            elif field.field_type in {
                                FormFieldType.TEXT,
                                FormFieldType.EMAIL,
                                FormFieldType.PHONE,
                                FormFieldType.URL,
                                FormFieldType.NUMBER,
                            }:
                                locator.fill(value, timeout=3000)
                            else:
                                continue
                            filled_ids.append(field_id)
                            filled_in_step.add(field_id)
                        if filled_in_step:
                            snapshot = snapshot.model_copy(update={
                                "fields": tuple(
                                    field.model_copy(update={"current_value_present": True})
                                    if field.id in filled_in_step else field
                                    for field in snapshot.fields
                                ),
                            })
                            snapshots[-1] = snapshot

                    if step_number >= max_steps:
                        break
                    unresolved = tuple(
                        field.id for field in snapshot.fields
                        if field.required and field.id not in filled_ids
                    )
                    next_action = next((item for item in snapshot.actions if item.continue_intent), None)
                    if next_action is None:
                        break
                    try:
                        assert_safe_next_action(
                            next_action,
                            required_fields_unresolved=unresolved,
                            visible_actions=snapshot.actions,
                        )
                    except BrowserSafetyError:
                        break
                    # This is the sole action that may click: exact Next/Continue,
                    # an explicit non-submit button, resolved required controls,
                    # and an empty submission-action scan. The network route is
                    # already fail-closed once any field was filled or the button is clicked.
                    interacted = True
                    if next_action.click_ordinal is None:
                        break
                    action_locator = page.locator("button, [role='button']").nth(next_action.click_ordinal)
                    if not action_locator.is_visible():
                        break
                    actual_label = " ".join((action_locator.inner_text() or "").split())
                    if actual_label.casefold() != next_action.label.casefold():
                        break
                    live_control = action_locator.evaluate(
                        "el => ({tag: el.tagName.toLowerCase(), type: el.type || '', role: el.getAttribute('role') || ''})"
                    )
                    if next_action.control_type == "button" and not (
                        live_control["tag"] == "button" and live_control["type"] == "button"
                    ):
                        break
                    if next_action.control_type == "button-role" and live_control["role"] != "button":
                        break
                    previous_signature = _form_signature(page.url, page.evaluate(_DOM_INSPECT_SCRIPT))
                    action_locator.click(timeout=2500, no_wait_after=True)
                    page.wait_for_timeout(150)
                if not snapshots:
                    manual_reason = manual_reason or ManualInterventionReason.NO_VISIBLE_FORM
                    snapshots.append(snapshot_from_dom_records(
                        url=page.url,
                        records=(),
                    ).model_copy(update={
                        "manual_intervention_required": True,
                        "manual_intervention_reason": manual_reason,
                    }))
            finally:
                context.close()
                browser.close()
        return BrowserRunResult(
            snapshots=tuple(snapshots),
            mappings=tuple(mappings),
            filled_safe_field_ids=tuple(filled_ids),
            advanced_steps=max(0, len(snapshots) - 1),
            manual_intervention_reason=manual_reason,
        )
