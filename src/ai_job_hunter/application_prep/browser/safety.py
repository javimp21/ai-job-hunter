"""Hard limits for actions exposed by the assisted browser workflow."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

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


class NavigationTrust(StrEnum):
    EXPECTED_ORIGIN = "EXPECTED_ORIGIN"
    ALLOWED_REDIRECT = "ALLOWED_REDIRECT"
    UNEXPECTED_ORIGIN = "UNEXPECTED_ORIGIN"


@dataclass(frozen=True, slots=True)
class CanonicalApplicationURL:
    scheme: str
    hostname: str
    port: int
    path: str

    @property
    def origin(self) -> tuple[str, str, int]:
        return self.scheme, self.hostname, self.port

    @property
    def url(self) -> str:
        port = f":{self.port}" if self.port != 443 else ""
        return urlunsplit((self.scheme, f"{self.hostname}{port}", self.path, "", ""))


_ATS_DOMAINS = {
    ATSProvider.GREENHOUSE: ("greenhouse.io",),
    ATSProvider.LEVER: ("lever.co",),
    ATSProvider.ASHBY: ("ashbyhq.com",),
}
# Lever documents separate global and EU hosted job sites. A cross-origin
# redirect is accepted only between these exact hosts and for the same job path.
_ALLOWED_REDIRECT_HOSTS = {
    ATSProvider.LEVER: frozenset({"jobs.lever.co", "jobs.eu.lever.co"}),
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


def canonicalize_application_url(url: str) -> CanonicalApplicationURL:
    """Canonical URL identity without query/fragment or a trailing slash."""

    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        raise BrowserSafetyError("Only HTTPS application URLs for a supported ATS are accepted.") from None
    validate_application_url(url)
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    path = parsed.path.rstrip("/") or "/"
    return CanonicalApplicationURL(
        scheme=parsed.scheme.casefold(),
        hostname=hostname,
        port=port or 443,
        path=path,
    )


def classify_navigation_url(initial_url: str, candidate_url: str) -> NavigationTrust:
    """Classify a navigation using canonical origin and narrow ATS redirect rules."""

    try:
        provider = validate_application_url(initial_url)
        if validate_application_url(candidate_url) is not provider:
            return NavigationTrust.UNEXPECTED_ORIGIN
        initial = canonicalize_application_url(initial_url)
        candidate = canonicalize_application_url(candidate_url)
    except BrowserSafetyError:
        return NavigationTrust.UNEXPECTED_ORIGIN
    if initial.origin == candidate.origin:
        return NavigationTrust.EXPECTED_ORIGIN
    allowed_hosts = _ALLOWED_REDIRECT_HOSTS.get(provider, frozenset())
    if (
        initial.hostname in allowed_hosts
        and candidate.hostname in allowed_hosts
        and initial.path == candidate.path
    ):
        return NavigationTrust.ALLOWED_REDIRECT
    return NavigationTrust.UNEXPECTED_ORIGIN


def is_safe_application_popup(initial_url: str, candidate_url: str) -> bool:
    """A popup is adoptable only for the same canonical application path."""

    if classify_navigation_url(initial_url, candidate_url) is NavigationTrust.UNEXPECTED_ORIGIN:
        return False
    try:
        return canonicalize_application_url(initial_url).path == canonicalize_application_url(candidate_url).path
    except BrowserSafetyError:
        return False


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
        canonicalize_application_url(url)
        canonicalize_application_url(initial_url)
        provider = detect_ats(initial_url)
    except BrowserSafetyError:
        return NetworkDecision.BLOCK
    if _is_submission_endpoint(url):
        return NetworkDecision.BLOCK
    if detect_ats(url) is not provider:
        return NetworkDecision.BLOCK
    if interacted_with_page:
        return NetworkDecision.BLOCK
    if is_navigation:
        if classify_navigation_url(initial_url, url) is NavigationTrust.UNEXPECTED_ORIGIN:
            return NetworkDecision.BLOCK
        return NetworkDecision.ALLOW
    try:
        if canonicalize_application_url(url).origin != canonicalize_application_url(initial_url).origin:
            return NetworkDecision.BLOCK
    except BrowserSafetyError:
        return NetworkDecision.BLOCK
    if resource_type.casefold() in {"websocket", "eventsource"}:
        return NetworkDecision.BLOCK
    return NetworkDecision.ALLOW


_SUBMISSION_ENDPOINT_RE = re.compile(
    r"(?:^|/)(?:submit(?:-application)?|submitapplication|submission|send-application|"
    r"application-submit|apply/submit)(?:/|$)", re.I
)
_SUBMISSION_QUERY_VALUE_RE = re.compile(r"^(?:submit|apply|send)(?:[-_ ]?application)?$", re.I)


def _is_submission_endpoint(url: str) -> bool:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return True
    if _SUBMISSION_ENDPOINT_RE.search(unquote(parsed.path)):
        return True
    return any(
        key.casefold() in {"action", "operation", "method", "event"}
        and _SUBMISSION_QUERY_VALUE_RE.fullmatch(value.strip()) is not None
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    )


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
