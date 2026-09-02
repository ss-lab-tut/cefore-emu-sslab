# Failure config resolves to an explicit policy

Status: accepted. Implementation is deferred to the R8 bundle.

The immediate fix for implicit host flapping changed omitted legacy `down_interval` /
`down_duration` values to resolve to no flapping. R8 should finish the design by
making failure behavior an explicit bootstrap decision instead of a runtime mix of
legacy args, structured dicts, and fallback defaults.

## Decision

Bootstrap will resolve failure configuration exactly once into a frozen
`FailurePolicy` dataclass. The policy mode is one of `none`, `simple`, or `cycles`.
After resolution, scenario code such as `disaster.py` must not inspect
`args.down_*` or raw `failure_scenarios` dictionaries.

Default values belong in the schema/config-resolution layer. Runtime failure code
must not inject fallback behavior with expressions such as `or 10`; those collapse
explicit zeroes and hide config intent.

YAML omission means `mode=none`. The literal value `failure_scenarios: none` is
allowed and is equivalent to omission. `failure_scenarios: {}` and
`failure_scenarios: null` are validation errors because they look like unfinished
configuration blocks.

In the new schema, `duration` and `interval` must be integers greater than or equal
to 1. A first-class "permanent down" expression is not part of this decision.
Likewise, schedulable `host_down` / `host_up` events remain future work.

Legacy `down_count` currently has two roles: flap count and cache fallback input
for `cache_count == 0`, where the cache-node count becomes `down_count + 1`. For
that reason, the immediate fix did not change the `down_count` default to zero.
R8 must remove or replace that coupling at the same time as it removes legacy
failure flags.

## R8 Migration

- Remove the four legacy `down_*` `OptionSpec` entries.
- Remove `periodic_host_flap` and route all failure execution through
  `FlexibleFailureManager` or its replacement behind `FailurePolicy`.
- Migrate `min_failure.yaml` to `failure_scenarios` and update the smoke-checker
  expectations for host down/up evidence.
- Update summarizer metadata handling for the removed legacy `down_*` keys.
- Redesign the default cache policy at the same time, including the
  `cache_count` / `down_count + 1` fallback.

## Consequences

Scenario code gets a narrow failure interface, and omitted failure configuration
stays visibly inert. The migration is intentionally bundled because failure
defaults, legacy cache fallback, smoke evidence, and metadata columns are coupled
today; changing only one of them would create silent behavior drift.

## Status note (2026-09-02)

Implementation is still deferred. Two points where the code has drifted from
the wording above, to be settled when R8 starts:

- The legacy `down_*` `OptionSpec` entries are five, not four:
  `down_interval`, `down_duration`, `down_exclude`, `down_count`,
  `down_stagger`.
- The validator's current `failure_scenarios.strategy` set is
  `simple / cyclic / random / manual`. The decision names the cycle mode
  `cycles`; `random` and `manual` are not mentioned. R8 must decide whether
  they become `FailurePolicy` modes or a separate policy, and reconcile the
  spelling.
