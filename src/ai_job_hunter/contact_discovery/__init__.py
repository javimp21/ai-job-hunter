"""Provider-injected, conservative contact discovery primitives.

This package contains no network client and performs no automatic outreach.
Concrete providers are supplied by callers; the bundled implementations are
manual and deterministic test providers only.
"""

from ai_job_hunter.contact_discovery.domain import (
    ContactCandidate,
    ContactLookupResult,
    ContactMatch,
    ContactMatchDecision,
    ContactMatchSignals,
    ContactPossibleMatch,
    ContactStrongDuplicate,
)
from ai_job_hunter.contact_discovery.matching import (
    canonical_linkedin_profile_url,
    match_contacts,
    normalize_contact_email,
)
from ai_job_hunter.contact_discovery.protocol import ContactProvider
from ai_job_hunter.contact_discovery.providers import (
    FakeContactProvider,
    ManualContactProvider,
)
from ai_job_hunter.contact_discovery.strategy import ContactLookupStrategy

__all__ = [
    "ContactCandidate",
    "ContactLookupResult",
    "ContactLookupStrategy",
    "ContactMatch",
    "ContactMatchDecision",
    "ContactMatchSignals",
    "ContactPossibleMatch",
    "ContactProvider",
    "ContactStrongDuplicate",
    "FakeContactProvider",
    "ManualContactProvider",
    "canonical_linkedin_profile_url",
    "match_contacts",
    "normalize_contact_email",
]
