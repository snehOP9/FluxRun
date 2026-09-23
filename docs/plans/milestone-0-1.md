# Milestone 0–1 implementation plan

## Outcome

A developer can boot FluxRun with Docker Compose, sign in to a seeded local owner account, create a workspace, and create/archive projects. All scoped data is checked against server-side workspace membership.

## Repository

```text
apps/api       FastAPI, SQLAlchemy, Alembic, API tests
apps/web       Vite React client
apps/worker    Reserved worker process with a health loop
packages/sdk-python  typed SDK configuration skeleton
docs/decisions authentication decision record
```

## Dependencies

- Python 3.12; FastAPI 0.141.1; SQLAlchemy 2.0.54; Pydantic 2.12.5; Alembic 1.17.2; psycopg 3.2.12; Argon2-cffi 25.1.0; Redis 6.4.0.
- Node 24; React 19.2.0; Vite 8.3.0; TypeScript 5.9.3.
- Docker services: PostgreSQL 17, Redis 8, MinIO, API, worker, and Vite web server.

## Data and API contract

Entities: users, sessions, workspaces, workspace_memberships, projects, audit_events. UUIDs are externally visible; all timestamps are UTC.

Routes: `GET /healthz`, `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`, `GET|POST /api/v1/workspaces`, `GET|POST /api/v1/workspaces/{workspace_id}/projects`, `PATCH /api/v1/projects/{project_id}`, and `POST /api/v1/projects/{project_id}/archive`.

## Security and tests

Argon2id password hashes; opaque hashed sessions in HttpOnly cookies; origin enforcement for mutations; Redis-backed login rate limits; authorization tests for cross-workspace access; FastAPI route tests; React type/build checks; Compose health checks; manual sign-in/create-workspace/create-project verification.

