"""Session cookies must remain secure in production even if the flag is omitted."""

from types import SimpleNamespace
from fastapi import Response
from fluxrun_api import security


def test_production_session_cookie_is_always_secure(monkeypatch):
    monkeypatch.setattr(security, "get_settings", lambda: SimpleNamespace(
        environment="production", session_cookie_secure=False, session_ttl_hours=1
    ))
    response = Response()
    security.set_session_cookie(response, "test-token")
    cookie = response.headers["set-cookie"].lower()
    assert "secure" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


def test_local_development_can_use_insecure_http_cookie(monkeypatch):
    monkeypatch.setattr(security, "get_settings", lambda: SimpleNamespace(
        environment="development", session_cookie_secure=False, session_ttl_hours=1
    ))
    response = Response()
    security.set_session_cookie(response, "test-token")
    cookie = response.headers["set-cookie"].lower()
    assert "secure" not in cookie
    assert "httponly" in cookie
