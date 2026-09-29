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
    NavigationTrust,
    NetworkDecision,
    SUBMIT_GUARD_INIT_SCRIPT,
    assert_safe_next_action,
    canonicalize_application_url,
    classify_navigation_url,
    is_safe_application_popup,
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
    const questionContainer = el.closest('.application-question, [data-question], [role="group"]');
    const fieldset = el.closest('fieldset');
    const question = questionContainer || (fieldset?.querySelector('legend') ? fieldset : null);
    const legend = question?.querySelector('legend');
    const questionLabel = question?.querySelector(
      ':scope > [data-question-label], :scope > .application-question-label, :scope > .application-question__label, :scope > .question-label, :scope > label'
    );
    const applicationLabel = question?.querySelector('.application-label');
    const applicationPrompt = applicationLabel?.querySelector('.text') || applicationLabel;
    const promptText = applicationPrompt
      ? [...applicationPrompt.childNodes]
          .filter(node => !(node.nodeType === Node.ELEMENT_NODE && node.matches('.required')))
          .map(node => node.nodeType === Node.TEXT_NODE ? node.textContent : text(node))
          .join(' ').replace(/[✱*]/g, ' ').replace(/\s+/g, ' ').trim()
      : '';
    const dataQuestion = question?.getAttribute('data-question') || '';
    const groupText = (legend && text(legend)) || (questionLabel && text(questionLabel)) || promptText ||
      (dataQuestion && dataQuestion !== 'true' ? dataQuestion : '') || question?.getAttribute('aria-label') || '';
    const ownLabel = labelText || labelledBy || aria || placeholder || '';
    const label = (groupText || ownLabel)
      .replace(/[✱*]/g, ' ')
      .replace(/\s+attach\s+resume\/cv\b.*$/i, '')
      .replace(/\s+/g, ' ').trim();
    const labelSource = labelText || labelledBy || groupText ? 'label' : aria ? 'aria' : placeholder ? 'placeholder' : 'attribute';
    const type = el.tagName === 'SELECT' ? (el.multiple ? 'multiple' : 'select') : el.tagName === 'TEXTAREA' ? 'textarea' : (el.type || 'text');
    const current = el.type === 'checkbox' || el.type === 'radio' ? !!el.checked : el.value !== undefined && String(el.value).length > 0;
    return {
      tag: el.tagName.toLowerCase(), type, id: el.id || el.name || `field-${ordinal + 1}`,
      name: el.name || '', label, group_label: groupText,
      option_label: el.type === 'radio' || el.type === 'checkbox' ? ownLabel : '', label_source: labelSource, visible: visible(el),
      option_ordinal: el.type === 'radio' || el.type === 'checkbox' ? ordinal : null,
      required: !!el.required || el.getAttribute('aria-required') === 'true' ||
        !!question?.querySelector('.required') || !!question?.classList.contains('required-field') ||
        Array.from(el.labels || []).some(label => !!label.querySelector('.required')),
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
        control_type: inputControl ? 'submit' : el.tagName === 'BUTTON'
          ? (el.getAttribute('type') || (el.form ? 'submit' : 'button')) : 'button-role',
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
    captcha_detected: Array.from(document.querySelectorAll('[id*="captcha" i], [class*="captcha" i], iframe[src*="captcha" i], iframe[src*="recaptcha" i]')).some(visible),
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


def _arm_dom_transition_observer(page) -> None:
    page.evaluate(r"""() => {
      window.__aiJobHunterTransitionObserver?.disconnect();
      window.__aiJobHunterTransitionCount = 0;
      window.__aiJobHunterLastTransition = 0;
      const observer = new MutationObserver(() => {
        window.__aiJobHunterTransitionCount += 1;
        window.__aiJobHunterLastTransition = performance.now();
      });
      observer.observe(document.documentElement || document, {
        attributes: true, childList: true, subtree: true
      });
      window.__aiJobHunterTransitionObserver = observer;
    }""")


def _wait_for_form_transition(page, previous_url: str) -> bool:
    """Wait for an actual URL/DOM transition and a brief DOM quiet period."""

    try:
        page.wait_for_function(
            "oldUrl => location.href !== oldUrl || (window.__aiJobHunterTransitionCount || 0) > 0",
            arg=previous_url,
            timeout=5000,
            polling=50,
        )
        if page.url != previous_url:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        else:
            page.wait_for_function(
                "() => performance.now() - (window.__aiJobHunterLastTransition || 0) >= 200",
                timeout=5000,
                polling=50,
            )
        return True
    except Exception:
        return False


def _adopt_safe_popup(context, current_page, *, initial_url: str, seen_page_ids: set[int]):
    candidates = [candidate for candidate in context.pages if id(candidate) not in seen_page_ids]
    if not candidates:
        return current_page, None
    if len(candidates) != 1:
        return current_page, ManualInterventionReason.UNEXPECTED_PAGE
    candidate = candidates[0]
    if candidate.url.casefold() in {"", "about:blank"}:
        try:
            candidate.wait_for_url(
                lambda observed: observed.casefold() not in {"", "about:blank"},
                wait_until="domcontentloaded",
                timeout=8000,
            )
        except Exception:
            return current_page, ManualInterventionReason.UNEXPECTED_PAGE
    try:
        candidate.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        return current_page, ManualInterventionReason.UNEXPECTED_PAGE
    if not is_safe_application_popup(initial_url, candidate.url):
        return current_page, ManualInterventionReason.UNEXPECTED_PAGE
    seen_page_ids.add(id(candidate))
    return candidate, None


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
    redirects_observed: tuple[str, ...] = ()
    would_fill_field_ids: tuple[str, ...] = ()
    would_skip_field_ids: tuple[str, ...] = ()
    needs_input_field_ids: tuple[str, ...] = ()

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
        dry_run: bool = False,
        max_steps: int = 5,
    ) -> BrowserRunResult:
        provider = validate_application_url(url, expected_ats)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise BrowserSafetyError(
                'Install browser support with `python -m pip install -e ".[browser]"` '
                "and install Chromium with `python -m playwright install chromium`."
            ) from error

        try:
            return self._run(
                sync_playwright,
                url=url,
                provider=provider,
                plan_for_snapshot=plan_for_snapshot,
                fill_safe=fill_safe,
                dry_run=dry_run,
                max_steps=max_steps,
            )
        except BrowserSafetyError:
            raise
        except Exception as error:
            # Exception text can contain URLs, form values, or browser payloads.
            raise BrowserSafetyError(
                f"Browser inspection stopped safely ({type(error).__name__}). No form data was logged."
            ) from None

    def _run(self, sync_playwright, *, url, provider, plan_for_snapshot, fill_safe, dry_run=False, max_steps=5):
        snapshots: list[ApplicationFormSnapshot] = []
        mappings: list[FieldMapping] = []
        filled_ids: list[str] = []
        redirects_observed: list[str] = []
        interacted = False
        manual_reason: ManualInterventionReason | None = None
        would_fill_ids: list[str] = []
        would_skip_ids: list[str] = []
        needs_input_ids: list[str] = []
        previous_signature: tuple | None = None
        with sync_playwright() as playwright:
            try:
                # Dry-runs use real Chromium without requiring an interactive desktop.
                browser = playwright.chromium.launch(headless=dry_run)
            except Exception as error:
                if type(error).__name__ == "Error" and any(
                    marker in str(error).casefold()
                    for marker in ("executable doesn't exist", "executable does not exist", "browser was not found")
                ):
                    raise BrowserSafetyError(
                        "Playwright Chromium is not installed. Run `python -m playwright install chromium`."
                    ) from None
                raise
            context = browser.new_context(
                service_workers="block",
                accept_downloads=False,
                permissions=[],
            )
            context.add_init_script(SUBMIT_GUARD_INIT_SCRIPT)

            def guard_route(route):
                nonlocal manual_reason
                request = route.request
                is_navigation = request.is_navigation_request()
                if is_navigation and getattr(request, "redirected_from", None) is not None:
                    try:
                        redirect_url = canonicalize_application_url(request.url).url
                        initial_canonical = canonicalize_application_url(url).url
                        if redirect_url != initial_canonical and redirect_url not in redirects_observed:
                            redirects_observed.append(redirect_url)
                    except BrowserSafetyError:
                        pass
                decision = network_decision(
                    url=request.url,
                    method=request.method,
                    resource_type=request.resource_type,
                    is_navigation=is_navigation,
                    initial_url=url,
                    interacted_with_page=interacted,
                )
                if decision is NetworkDecision.ALLOW:
                    route.continue_()
                else:
                    if is_navigation and not interacted:
                        manual_reason = (
                            ManualInterventionReason.UNSUPPORTED_REDIRECT
                            if classify_navigation_url(url, request.url) is NavigationTrust.UNEXPECTED_ORIGIN
                            else ManualInterventionReason.NETWORK_POLICY
                        )
                    route.abort("blockedbyclient")

            context.route("**/*", guard_route)
            if hasattr(context, "route_web_socket"):
                context.route_web_socket("**/*", lambda socket: socket.close())
            page = context.new_page()
            seen_page_ids = {id(page)}
            try:
                navigation_failed = False
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=25000)
                except Exception:
                    navigation_failed = True
                    manual_reason = manual_reason or ManualInterventionReason.NETWORK_POLICY
                if not navigation_failed:
                    try:
                        page.wait_for_load_state("load", timeout=5000)
                    except Exception:
                        pass
                step_limit = 1 if dry_run and not navigation_failed else max(1, min(max_steps, 5)) if not navigation_failed else 0
                for step_number in range(1, step_limit + 1):
                    page, popup_reason = _adopt_safe_popup(
                        context,
                        page,
                        initial_url=url,
                        seen_page_ids=seen_page_ids,
                    )
                    if popup_reason is not None:
                        manual_reason = popup_reason
                        break
                    page_url = page.url
                    if classify_navigation_url(url, page_url) is NavigationTrust.UNEXPECTED_ORIGIN:
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
                    plan = plan_for_snapshot(snapshot, page_url)
                    mappings.extend(plan.mappings)
                    if dry_run:
                        mapping_by_id = {item.field_id: item for item in plan.mappings}
                        for field in snapshot.fields:
                            mapping = mapping_by_id.get(field.id)
                            if field.current_value_present:
                                would_skip_ids.append(field.id)
                            elif field.required and (
                                mapping is None or field.id not in plan.values_by_field_id
                            ):
                                needs_input_ids.append(field.id)
                            elif field.id in plan.values_by_field_id:
                                would_fill_ids.append(field.id)
                            elif not field.required:
                                would_skip_ids.append(field.id)
                    if snapshot.manual_intervention_required:
                        manual_reason = snapshot.manual_intervention_reason
                        break
                    if fill_safe:
                        filled_in_step: set[str] = set()
                        fields_by_id = {field.id: field for field in snapshot.fields}
                        for field_id, value in (() if dry_run else plan.values_by_field_id.items()):
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
                            elif field.field_type is FormFieldType.RADIO:
                                option_index = next((index for index, item in enumerate(field.options) if item.casefold() == value.casefold()), None)
                                if option_index is None or option_index >= len(field.option_ordinals):
                                    continue
                                option_locator = page.locator("input, select, textarea").nth(field.option_ordinals[option_index])
                                if not option_locator.is_visible() or not option_locator.is_editable():
                                    continue
                                option_locator.check(timeout=3000)
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

                    if dry_run or step_number >= max_steps:
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
                    previous_url = page.url
                    _arm_dom_transition_observer(page)
                    action_locator.click(timeout=2500, no_wait_after=True)
                    changed = _wait_for_form_transition(page, previous_url)
                    page, popup_reason = _adopt_safe_popup(
                        context,
                        page,
                        initial_url=url,
                        seen_page_ids=seen_page_ids,
                    )
                    if popup_reason is not None:
                        manual_reason = popup_reason
                        break
                    if not changed and page.url == previous_url:
                        break
                if not snapshots:
                    manual_reason = manual_reason or ManualInterventionReason.NO_VISIBLE_FORM
                    snapshots.append(snapshot_from_dom_records(
                        url=canonicalize_application_url(url).url,
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
            redirects_observed=tuple(redirects_observed),
            would_fill_field_ids=tuple(dict.fromkeys(would_fill_ids)),
            would_skip_field_ids=tuple(dict.fromkeys(would_skip_ids)),
            needs_input_field_ids=tuple(dict.fromkeys(needs_input_ids)),
        )
