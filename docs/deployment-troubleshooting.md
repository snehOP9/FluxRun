# Deployment Troubleshooting

## Before deploying

- Confirm the application root is correct.
- Install dependencies from the application directory.
- Run the production build locally.
- Confirm the output directory matches the hosting configuration.

## Common failures

### Build command not found

Check that the required build tool is declared in the application's `package.json` and that the deployment installs dependencies from the same directory.

### Wrong project root

For a monorepo, configure the hosting project to use the directory containing the application's `package.json`.

### Failed production build

Run the production build locally and inspect the first actionable error rather than the final exit message.

## Verification

After deployment, verify the deployment status, application URL, and production build output before considering the release complete.
