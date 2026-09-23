# ADR 0001: Database-backed opaque browser sessions

## Context

FluxRun needs browser authentication before SDK API keys exist. Stateless JWTs make revocation and session rotation needlessly indirect for the initial self-hosted release.

## Decision

Use a random 256-bit session token in an HttpOnly, SameSite=Lax cookie. Store only its SHA-256 digest, expiry, revocation time, and user ID in PostgreSQL. Rotate by issuing a new token on login; revoke on logout.

## Consequences

Sessions are immediately revocable and cannot be recovered from the database. API routes require a database lookup. SDK API keys remain a later Milestone feature.

