# Security Review Checklist

- Confirm passwords are never logged or stored in raw form.
- Confirm browser sessions use secure cookie attributes in HTTPS deployments.
- Confirm state-changing cookie-authenticated requests validate the Origin header.
- Confirm workspace-scoped routes enforce workspace authorization.
- Confirm login rate limiting is appropriate for the deployment topology.
- Confirm development-only Compose settings are not presented as production defaults.
- Review secrets and environment values before publishing a deployment.
