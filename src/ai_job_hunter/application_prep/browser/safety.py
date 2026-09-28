"""Hard limits for actions exposed by the assisted browser workflow."""

from __future__ import annotations

import re
from enum import StrEnum
from urllib.parse import urlsplit

from ai_job_hunter.application_prep.browser.models import (
    ATSProvider,
    FormAction,
)


class BrowserSafetyError(RuntimeError):
    """A browser action was refused by the local safety policy."""


class SubmissionBlockedError(BrowserSafetyError):
    """An action could send or finalize an application."""


class NetworkDecision(StrEnum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


_ATS_DOMAINS = {
    ATSProvider.GREENHOUSE: ("greenhouse.io",),
    ATSProvider.LEVER: ("lever.co",),
    ATSProvider.ASHBY: ("ashbyhq.com",),
}
_SUBMISSION_LABEL = re.compile(
    r"\b(?:submit|apply|send|complete|finish)\b",
    re.I,
)
_CONTINUE_LABEL = re.compile(r"^(?:next|continue)(?:\s+(?:to\s+)?(?:step\s+)?\d+)?$", re.I)


def detect_ats(url: str) -> ATSProvider:
    try:
        host = (urlsplit(url).hostname or "").casefold().rstrip(".")
    except ValueError:
        return ATSProvider.UNKNOWN
    for provider, domains in _ATS_DOMAINS.items():
        if any(host == domain or host.endswith(f".{domain}") for domain in domains):
            return provider
    return ATSProvider.UNKNOWN


def validate_application_url(url: str, expected_ats: ATSProvider | None = None) -> ATSProvider:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise BrowserSafetyError("Only HTTPS application URLs for a supported ATS are accepted.") from None
    provider = detect_ats(url)
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or (port is not None and port != 443)
        or provider is ATSProvider.UNKNOWN
        or (expected_ats is not None and expected_ats is not provider)
    ):
        raise BrowserSafetyError("Only HTTPS application URLs for a supported ATS are accepted.")
    return provider


def is_submission_intent(label: str, control_type: str = "button") -> bool:
    if control_type.strip().casefold() == "submit":
        return True
    return bool(_SUBMISSION_LABEL.search(" ".join(label.casefold().split())))


def make_form_action(label: str, control_type: str = "button") -> FormAction | None:
    clean_label = " ".join(label.split())
    if not clean_label:
        return None
    submit = is_submission_intent(clean_label, control_type)
    return FormAction(
        label=clean_label[:300],
        control_type=control_type[:40],
        submission_intent=submit,
        continue_intent=not submit and bool(_CONTINUE_LABEL.fullmatch(clean_label)),
    )


def assert_safe_next_action(
    action: FormAction,
    *,
    required_fields_unresolved: tuple[str, ...] = (),
    visible_actions: tuple[FormAction, ...] = (),
) -> None:
    """Permit only a narrowly identified Next/Continue action with no submit signal."""

    if action.submission_intent:
        raise SubmissionBlockedError("Submission-like browser actions are blocked.")
    if not action.continue_intent or action.control_type.casefold() not in {"button", "button-role"}:
        raise BrowserSafetyError("Only an exact Next or Continue button can advance a form.")
    if required_fields_unresolved:
        raise BrowserSafetyError("The current step has required fields that are not safely resolved.")
    if any(item.submission_intent for item in visible_actions):
        raise SubmissionBlockedError("A visible submission control makes step advancement ambiguous.")


def network_decision(
    *,
    url: str,
    method: str,
    resource_type: str,
    is_navigation: bool,
    initial_url: str,
    interacted_with_page: bool,
) -> NetworkDecision:
    """Allow page reads and static assets; block all writes and post-fill traffic."""

    normalized_method = method.upper()
    if normalized_method not in {"GET", "HEAD"}:
        return NetworkDecision.BLOCK
    try:
        requested = urlsplit(url)
        initial = urlsplit(initial_url)
    except ValueError:
        return NetworkDecision.BLOCK
    if requested.scheme.casefold() != "https" or requested.hostname is None:
        return NetworkDecision.BLOCK
    try:
        if requested.port != initial.port:
            return NetworkDecision.BLOCK
    except ValueError:
        return NetworkDecision.BLOCK
    if detect_ats(url) is ATSProvider.UNKNOWN or detect_ats(url) is not detect_ats(initial_url):
        return NetworkDecision.BLOCK
    if interacted_with_page:
        return NetworkDecision.BLOCK
    if is_navigation:
        # Only the explicitly requested first document can navigate. Redirects,
        # form actions and link-based progression require a human decision.
        if requested.hostname != initial.hostname or requested.path != initial.path or requested.query != initial.query:
            return NetworkDecision.BLOCK
        return NetworkDecision.ALLOW
    if resource_type.casefold() in {"websocket", "eventsource"}:
        return NetworkDecision.BLOCK
    return NetworkDecision.ALLOW


# Installed before page scripts. Browser code has no exposed generic click,
# keyboard, submit, file chooser, or JavaScript execution operation.
SUBMIT_GUARD_INIT_SCRIPT = r"""
(() => {
  const stop = event => { event.preventDefault(); event.stopImmediatePropagation(); };
  document.addEventListener('submit', stop, true);
  document.addEventListener('keydown', event => {
    if (event.key === 'Enter') stop(event);
  }, true);
  document.addEventListener('click', event => {
    const target = event.target instanceof Element
      ? event.target.closest('button, [role="button"], input[type="submit"], input[type="image"], input[type="button"]')
      : null;
    if (!target) return;
    const label = (target.innerText || target.value || target.getAttribute('aria-label') || '').trim();
    if (target.type === 'submit' || target.type === 'image' || /\b(submit|apply|send|complete|finish)\b/i.test(label)) stop(event);
  }, true);
  const blocked = () => { throw new Error('Application submission is disabled.'); };
  try { Object.defineProperty(HTMLFormElement.prototype, 'submit', { value: blocked, configurable: false }); } catch (_) {}
  try { Object.defineProperty(HTMLFormElement.prototype, 'requestSubmit', { value: blocked, configurable: false }); } catch (_) {}
  try { Object.defineProperty(Navigator.prototype, 'sendBeacon', { value: () => false, configurable: false }); } catch (_) {}
  try { Object.defineProperty(window, 'WebSocket', { value: function() { throw new Error('Network sockets are disabled.'); }, configurable: false }); } catch (_) {}
  try { Object.defineProperty(window, 'EventSource', { value: function() { throw new Error('Network events are disabled.'); }, configurable: false }); } catch (_) {}
})();
"""
