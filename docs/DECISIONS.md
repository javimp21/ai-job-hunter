# Decisions

Persistent architectural/product decisions.

Add entries only for decisions worth preserving across sessions.

## D001 — Repository is source of truth

Current code, configuration, tests and migrations override stale conversation context.

## D002 — Deterministic filtering before expensive reasoning

Hard constraints should normally be evaluated before Jev when they can be decided deterministically.

Reasons:

- lower cost;
- lower latency;
- reproducibility;
- explainability.

## D003 — Priority is not probability

`priority` represents review priority.

It must not be presented as probability of interview, offer or hiring.

## D004 — UNKNOWN is explicit

Missing information remains UNKNOWN until supported by evidence.

Do not infer values merely to complete a record.

## D005 — Human approval for external actions

Applications, outreach and other consequential external actions require explicit user authorization.

## D007 — Company Hunter is draft-and-suggest only

Company Hunter ranks companies, stores verifiable public contacts, drafts outreach and queues manual LinkedIn connections, but never sends to companies and never touches LinkedIn: connections are clicked by the candidate and the tool records what they report. Fit scores are review priority, hints earn partial credit, UNKNOWN scores 0. Generated text is limited to the base CV and checked in code (placeholders, unsupported technologies/numbers, 300-character LinkedIn note limit). Details: `docs/COMPANY_HUNTER.md`.

## D006 — Provenance matters

Company/job intelligence should retain enough source information to explain where claims originated.
