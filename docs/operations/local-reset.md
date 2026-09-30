# Local Reset

When a local development environment needs a clean start:

1. Stop the Compose services.
2. Remove only development data that is safe to recreate.
3. Start the stack again with `docker compose up --build`.
4. Check `/healthz` before opening the web application.

Keep production data and credentials outside this reset workflow.
