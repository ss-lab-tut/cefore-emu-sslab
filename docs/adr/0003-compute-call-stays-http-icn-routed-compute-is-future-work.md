# compute_call stays an edge-side HTTP client; ICN-routed compute is future work

Status: accepted (2026-07-16). The HTTP model is implemented; the ICN-routed
model is deliberately deferred.

## Context

compute_call emulates edge-compute offload: an edge node (a Jetson-class box,
or any compute resource on the LAN answering HTTP) receives a computation
request, and the result is republished into the ICN (`publish_uri` →
cefputfile) for other nodes to `get`.

Two call models were considered:

1. **Edge-side HTTP (chosen)** — the scenario event models "a computation
   request arrived at the edge at time t". The edge host performs the HTTP
   call itself; only the *result* travels the ICN. Fits the existing
   scheduler/EventOutcome/ResultsSink machinery; no daemon changes.
2. **ICN-routed request (deferred)** — the consumer expresses the request as
   an Interest (NFN / Compute-First-Networking style, e.g.
   `ccnx:/compute/req/...`), cefnetd forwards it toward the compute node,
   which executes the HTTP call on arrival and answers with the result.

## Decision

Keep compute_call as the edge-side HTTP client. The ICN-routed model needs a
request listener on the compute node (something must consume the Interest and
trigger execution — a cefapp-style daemon or a pubsub_sub loop), a
naming/encoding convention for requests, and a response path with lifetimes —
none of which the current event machinery provides. That is a separate design,
not an extension of this event type.

## Consequences / sketch for the future ICN-routed design

- Request channel: compute node runs a subscriber (`cefsubfile`-style loop or
  a dedicated cefapp) on a request prefix; consumers publish request payloads
  under it. Routing the *request* prefix toward the compute host needs its own
  FIB programming (the existing fib_add machinery); the current
  `publication_uri_field` metadata only maps the *response* `publish_uri`.
- Execution: on request receipt the compute node invokes the same
  `compute_client.compute_call()` (the HTTP seam is reusable as-is; the
  runner-injected `ComputeResult` interface was shaped for this).
- Response: republish under a response URI derived from the request name;
  consumers `get` it. Correlation and expiry policy (pub_opts) must be part
  of the naming convention.
- Evaluation: the tri-state outcome vocabulary (ok / not-ok /
  skipped-no-result) and the EventRecord detail dict carry over unchanged.

Do not grow the current compute_call event toward model 2 incrementally; when
the ICN-routed model is needed, design the request/response naming first.
