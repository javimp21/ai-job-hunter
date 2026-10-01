# Architecture

This document explains architectural boundaries and intent.

Do not duplicate information that can be obtained directly from the code or repository graph.

## Principles

- Deterministic rules should remain deterministic.
- LLM/Jev reasoning should be used where semantic judgment adds value.
- Expensive/external operations should happen as late as practical.
- Business logic belongs in backend/domain services, not UI.
- External integrations should have clear boundaries.
- Persist useful results when doing so avoids repeated expensive work.
- Prefer idempotent operations.

## Before architectural changes

Inspect:

1. current implementation;
2. callers and dependencies;
3. configuration;
4. tests;
5. persistence/migrations;
6. external side effects.

Record important long-term architectural choices in `DECISIONS.md`.
