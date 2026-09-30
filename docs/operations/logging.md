# Logging Guidance

Log events that help diagnose failures without exposing secrets.

- Include a request or job identifier when available.
- Prefer structured fields over long free-form messages.
- Never log passwords, session cookies, access tokens, or raw credentials.
- Keep error messages actionable while avoiding sensitive payloads.
