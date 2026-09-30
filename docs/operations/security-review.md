# Security Review

For changes affecting authentication, authorization, sessions, or external input, review the following before release:

- Validate all external input at the boundary.
- Confirm workspace authorization is enforced on scoped routes.
- Avoid logging credentials or session material.
- Review cookie and transport security settings.
- Add regression coverage for security-sensitive behavior.
