# Production Release Checklist

Use this checklist for each release. Check items only after performing them; record any skipped step and its reason.

## Before release

- [ ] Review the change set and confirm the intended base branch.
- [ ] Confirm dependency manifests and lockfiles are in sync.
- [ ] Review dependency/security alerts relevant to the change.
- [ ] Verify required environment variables are documented and configured in the target environment.
- [ ] Confirm no secrets, local environment files, personal data, or generated database dumps are included.
- [ ] Run the relevant automated tests, type checks, lint, and production build; record the exact commands and results.
- [ ] Review database migrations for backward compatibility, lock duration, and rollback implications.
- [ ] Confirm Docker Compose configuration parses: `docker compose config --quiet`.

## Deployment

- [ ] Confirm the target environment, project root, build command, start command, and deployment region.
- [ ] Deploy the intended commit and retain its commit SHA/deployment identifier.
- [ ] Verify service startup, database migration/bootstrap completion, and dependency readiness.
- [ ] Confirm the API health endpoint responds as expected.
- [ ] Check application logs for startup errors, crash loops, and repeated dependency failures.

## Post-deployment smoke checks

- [ ] Open the deployed web application and verify the main route.
- [ ] Exercise the key workflow changed by this release.
- [ ] Verify authentication and authorization boundaries for affected endpoints.
- [ ] Confirm persistence works where the release changes database behavior.
- [ ] Check browser/server logs for new errors.
- [ ] Confirm the deployment status and production URL, not only the build result.

## Rollback and closeout

- [ ] Identify the previous known-good deployment or commit before release.
- [ ] Confirm rollback instructions and any database migration constraints.
- [ ] If a smoke check fails, stop rollout and roll back when safe; do not declare success based only on a green build.
- [ ] Record the release commit, validation evidence, known risks, and follow-up issues.
