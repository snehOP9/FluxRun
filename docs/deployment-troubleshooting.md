# Deployment Troubleshooting

Use this guide to diagnose the first failing layer. Do not treat a container being "running" as proof that the application is ready.

## 1. Confirm configuration and project root

- Run commands from the repository root unless a command explicitly names a service directory.
- Copy `.env.example` to `.env` and replace every `replace-...` placeholder with local-only values.
- Never commit `.env`, production credentials, tokens, or database dumps.
- Check that Docker Compose can resolve the configuration before building:

  ```bash
  docker compose config --quiet
  ```

If this fails, inspect missing variables and YAML indentation before investigating the application.

## 2. Build and start services

```bash
docker compose up --build -d
docker compose ps
docker compose logs --tail=200 api
docker compose logs --tail=200 worker
docker compose logs --tail=200 web
```

Use the actual service names shown by `docker compose config --services` if they differ. Inspect the earliest error in the failing service's logs; later connection errors may only be consequences.

## 3. Common failures

### Dependency or build failure

Rebuild the affected service and inspect the first package-manager/compiler error:

```bash
docker compose build api
```

For frontend failures, use the web service's build command and logs. Confirm the Docker build context and Dockerfile path match the intended app directory.

### Database connection or migration failure

- Confirm the database container is healthy: `docker compose ps`.
- Check the database logs and the effective Compose environment.
- Verify the database name, username, password, and service hostname agree.
- Remember that containers should connect to the Compose service hostname and container port, not the host-published port.
- Do not run destructive reset commands against data you need to keep.

### Redis or object-storage failure

Check service health and logs for Redis and MinIO. Verify that API/worker environment values use the internal service hostnames and that the configured bucket/credentials exist. Do not expose MinIO credentials in issue reports.

### API is running but requests fail

- Probe `http://localhost:8000/healthz`.
- Inspect API logs for migration, bootstrap, validation, or authentication errors.
- Confirm browser requests use the expected API URL and that cookies use secure settings only when the deployment is served over HTTPS.
- A successful health response does not prove every integration is working; exercise the affected endpoint too.

### Deployment platform reports the wrong output or root

Confirm the platform's root directory, install command, build command, start command, and output directory against the actual application. Reproduce the production build locally before changing configuration.

## 4. Verify recovery

After a correction:

1. Rebuild/restart only the affected services where possible.
2. Confirm `docker compose ps` shows expected state.
3. Check the health endpoint and the relevant user workflow.
4. Inspect logs for repeated restarts, migrations, and connection failures.
5. Record the root cause and the exact verification performed.

When asking for help, include the failing service, sanitized logs around the first error, the command used, and whether the failure reproduces locally. Redact credentials, cookies, tokens, and personal data.
