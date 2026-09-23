# FluxRun

FluxRun is an original, self-hostable engineering evidence platform for experiments and AI systems. The local build includes secure bootstrap, cookie sessions, workspace authorization, tracking, artifacts, registries, tracing, evaluations, reviews, a Python SDK, and a usable web shell.

## Start locally

1. Copy `.env.example` to `.env` and replace every `replace-...` value.
2. Run `docker compose up --build`.
3. Open `http://localhost:5173` and sign in with `LOCAL_ADMIN_EMAIL` and `LOCAL_ADMIN_PASSWORD`.

The API health endpoint is `http://localhost:8000/healthz`; API documentation is at `/docs`.

## Current status

Implemented locally: authentication and workspace authorization; experiments, runs, immutable parameters, idempotent metric batches, S3-backed artifacts, model/prompt/dataset/evaluation registries, lineage, trace redaction and async context propagation, Celery-backed evaluations, review queues, webhooks, and the Python SDK.

The Compose worker must run the Celery command in `docker-compose.yml`; the lightweight `fluxrun_worker.main` loop is only a connectivity probe.

Validated locally: API unit tests, web typecheck/build, tracking integration, advanced evaluation/registry/tracing/SDK integration, and the browser workflow with responsive and WCAG checks.

## Security notes

- Passwords are hashed with Argon2id; raw passwords are never logged or stored.
- Browser sessions are random, hashed server-side, HttpOnly, SameSite=Lax cookies.
- State-changing cookie-authenticated requests require a same-origin `Origin` header.
- Workspace access is enforced on every scoped route.
- Login attempts are rate-limited in-process for local development; production needs an equivalent shared edge or Redis policy before using multiple API replicas.
- The compose setup is development-only. `SESSION_COOKIE_SECURE=true` is required behind HTTPS in production.

See `docs/plans/milestone-0-1.md` and `docs/decisions/0001-session-auth.md` for the implementation contract.
