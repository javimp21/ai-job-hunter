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

## D006 — Provenance matters

Company/job intelligence should retain enough source information to explain where claims originated.
