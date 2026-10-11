# Contributing

Thanks for helping improve FluxRun.

## Workflow

1. Check existing issues and pull requests before starting.
2. Create a focused branch for one problem.
3. Keep behavior changes covered by tests or a reproducible verification step.
4. Update documentation when configuration, APIs, deployment, or user workflows change.
5. Use a clear commit message that describes the change, not the activity.
6. Open a pull request with the problem, implementation, verification, and any operational impact.

## Local verification

Start from the setup in [local-development.md](local-development.md). Before requesting review:

- confirm the API health endpoint responds;
- run the relevant API/web/SDK tests for the files changed;
- run type-checking or linting where applicable;
- confirm no credentials, local `.env` files, artifacts, or generated data are included.

## Security-sensitive changes

Authentication, session handling, workspace authorization, webhooks, artifact access, tracing/redaction, and secret handling require explicit regression coverage. Do not weaken production defaults to make local development easier.

## Pull-request scope

Prefer small, reviewable pull requests. If a change requires a migration, compatibility break, or deployment step, call that out clearly in the PR description.
