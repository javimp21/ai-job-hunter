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

## Explicit experience requirements

Experience years are extracted conservatively from public descriptions, independently of title seniority. Explicit upper bounds such as “up to 3 years” are not treated as minimum requirements. Section headings such as `Requirements`, `Required experience`, `Desired qualifications` and `Additional qualifications` preserve mandatory versus preferred provenance. The comparison runs before Jev and is rechecked when displaying cached opportunities or selecting notifications.

Candidate preferences configure two non-negative, candidate-relative tolerances:

- `experience_floor_shortfall_tolerance`: **2 years** by default;
- `experience_range_shortfall_tolerance`: **1 year** by default.

For a candidate with one year, a mandatory minimum of `3` or `3+` years is a **STRETCH / REVIEW**, while `3–5`, `3 to 5+`, or a minimum of `4+` years is **SKIP**. The stricter range tolerance is a search preference, not a claim that hiring requirements are universally rigid. Range upper endpoints are not automatically disqualifying maximums; an explicit “less than two years” is an upper bound, not a two-year minimum.

Preferred/nice-to-have years never become mandatory constraints. Missing/ambiguous experience, unknown candidate tenure, and unverified experience in a particular role/technology remain **UNKNOWN**. Both STRETCH and UNKNOWN cap the final decision at REVIEW, even with strong Jev signals; numeric fit never overrides other hard constraints.

The local feed shows the public requirement, evidence and any numerical shortfall. Telegram includes public requirements and generic concerns, never the candidate's years or numerical personal gap. UNKNOWN reviews are not globally hidden by this change.

Historical evaluations and notification ledger rows are preserved. The new prefilter version invalidates old semantic decisions; incompatible current requirements can still produce a read-only SKIP projection. Other legacy results remain STALE until a normal authorized evaluation/cache hit replaces them. No unproven legacy evidence migration or automatic external reevaluation is performed. `refresh --no-jev` still fetches live boards; it is not an offline backfill command.

## Role families

The prefilter classifies the title (English or Spanish, accents ignored) into a role family. Only explicit title evidence is used; the description is left to Jev.

- **TARGET** — software, backend, platform or infrastructure engineering, including backend/software titles in an AI domain (`Software Engineer, AI`, `Backend Engineer - GenAI`). `Back End` and `Fullstack` spellings match `Backend` and `Full Stack`.
- **POTENTIALLY_RELEVANT** — families whose fit depends on the actual work: data/analytics engineering, AI engineering (`AI`, `Applied AI`, `LLM`, `GenAI` engineer), AI/ML platform, machine learning engineering, vision/NLP/deep-learning engineering, research engineering, and customer-facing engineering (field, solutions, FDE). These are never rejected by title; the family adds a review reason, so they cannot PASS the prefilter on title alone. A Data Engineer is reviewed, not rejected, because platform/pipeline work can fit.
- **NON_TARGET** — hard SKIP without Jev: sales (`ventas`), HR, legal, marketing, design, finance, product, operations, unscoped applications, and titles without an engineering noun (`engineer`, `developer`, `ingeniero`, `desarrollador`, `programador`…) that are governance/risk/compliance, analyst, or scientist/researcher roles. A technical domain word such as `Security` or `Data` does not rescue them. ML research engineering (`ML Research Engineer`) is also non-target.
- **UNKNOWN** — other titles; the preferred-role signal still applies.

Adding a family never relaxes APPLY: experience, geography, seniority and the Jev policy gates still apply.

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
