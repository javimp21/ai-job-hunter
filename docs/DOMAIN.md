# Job Domain

Rules for job discovery, filtering and decisions.

## Decision states

The system may classify opportunities as:

- APPLY
- REVIEW
- SKIP

Do not loosen APPLY thresholds merely to produce more APPLY results.

## Hard constraints

Respect current configured constraints for:

- geography;
- seniority;
- role relevance;
- other explicit candidate requirements.

Inspect current configuration before changing them.

## Priority

`priority` means review priority.

It is not:

- hiring probability;
- interview probability;
- model confidence.

## Unknown information

Use UNKNOWN when evidence is insufficient.

Do not infer:

- salary;
- seniority;
- remote eligibility;
- technologies;
- location compatibility;

without adequate evidence.

## Changes

Changes affecting filtering, seniority, geography or decisions require relevant regression tests.
