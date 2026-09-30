# Testing Guidance

Run the smallest useful test set first, then expand coverage when a change crosses subsystem boundaries.

- Unit tests cover isolated logic.
- Integration tests cover service boundaries.
- Browser tests cover critical user workflows.
- Security-sensitive changes should include regression tests.

Record failures with enough context to reproduce them locally.
