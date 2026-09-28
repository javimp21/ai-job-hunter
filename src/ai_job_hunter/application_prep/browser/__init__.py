"""Optional, assisted-only browser inspection for application forms.

Importing this package has no browser, network, filesystem, or Playwright side
effects. Playwright is imported lazily by the explicit browser command.
"""

from ai_job_hunter.application_prep.browser.models import (
    ApplicationFormSnapshot,
    ApplicationSession,
    ApplicationSessionStatus,
    ATSProvider,
    FieldMapping,
    FormField,
    FormFieldType,
)

__all__ = [
    "ApplicationFormSnapshot",
    "ApplicationSession",
    "ApplicationSessionStatus",
    "ATSProvider",
    "FieldMapping",
    "FormField",
    "FormFieldType",
]
