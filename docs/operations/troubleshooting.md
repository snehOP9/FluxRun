# Troubleshooting

If the local stack is unavailable:

1. Confirm the Compose services are running.
2. Check the API health endpoint.
3. Inspect the service logs for the first reported error.
4. Verify required environment variables are configured.
5. Restart only the affected development service before rebuilding the whole stack.

When reporting a failure, include the failing endpoint, relevant log message, and the latest change that preceded it.
