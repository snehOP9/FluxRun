# Local Development

## Prerequisites

- Docker Desktop or Docker Engine with Compose v2
- Git
- Enough local resources to run the API, web app, PostgreSQL, Redis, MinIO, and worker services

## First run

1. Clone the repository and enter the project directory.
2. Copy `.env.example` to `.env`.
3. Replace every `replace-...` placeholder with a local-only value.
4. Build and start the stack:

```bash
docker compose up --build
```

5. Open `http://localhost:5173` and sign in with the configured `LOCAL_ADMIN_EMAIL` and `LOCAL_ADMIN_PASSWORD`.

## Verify the stack

Check the API before debugging the browser:

```bash
curl http://localhost:8000/healthz
```

FastAPI documentation is available at `http://localhost:8000/docs`.

If a service fails, inspect it directly instead of restarting everything blindly:

```bash
docker compose ps
docker compose logs api --tail=100
docker compose logs worker --tail=100
```

## Resetting local state

Stop the stack with `docker compose down`. Use `docker compose down -v` only when you intentionally want to delete local database/object-storage volumes and start from empty state.

## Before opening a pull request

Run the checks relevant to the changed component and confirm the Compose stack still reaches `/healthz`. Do not commit `.env`, credentials, generated secrets, or local data volumes.
