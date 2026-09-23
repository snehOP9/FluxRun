# Full build continuation

The accepted scope is Milestones 0–11 (required tiers 0–3). Tier 4 gateway,
OTLP, SSO and Kubernetes remain optional follow-on work as specified in the brief.

1. Repair foundation and start PostgreSQL, Redis and S3; verify login, membership
   isolation and working browser navigation against the real stack.
2. FR-013, FR-020–033: scoped keys; experiments/runs; immutable parameters;
   idempotent metric batches; buffered SDK; streamed S3 artifacts; compare.
3. FR-040–044: dataset versions and lineage, safe environment capture, model
   versions allocated under row locks, compare-and-swap aliases and audit.
4. FR-050–055: deterministic prompt templates, immutable versions/diffs,
   native trace SDK, validation/redaction, trace tree and parallel timeline.
5. FR-060–064: immutable evaluation cases, predefined scorers, durable job
   snapshots dispatched through Celery/Redis, results/comparison, review claims.
6. FR-070–075: PostgreSQL/S3 integration tests, browser workflows and accessibility,
   measured load checks, CI, production Compose, backups/restore and screenshots.

Each stage adds a migration, bounded API schemas, explicit project authorization,
real frontend queries, risky-behavior tests, and evidence in PROJECT_STATUS.md.
The working backlog is this file plus that status report; no external issues or
publishing are needed to implement and run the project locally.
