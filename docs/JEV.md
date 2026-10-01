# Jev

## Principle

Use Jev when semantic judgment is actually required.

Do not make new Jev calls merely to inspect or test unrelated behavior.

## Prefer

When possible use:

1. persisted results;
2. cache;
3. fixtures;
4. mocks;
5. live Jev only when required.

## Tests

Offline tests must not silently perform live Jev calls.

Clearly distinguish:

- offline test;
- local smoke test;
- live fetch;
- live Jev.

## Decision pipeline

Do not move deterministic constraints into Jev without a concrete reason.

Do not change prompts/policies casually: inspect existing evaluations and regression coverage first.

## Reporting

State explicitly when a result came from live Jev versus cached/fixture data.
