import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import get_settings
from .models import SessionToken, User

password_hasher = PasswordHasher()
SESSION_COOKIE = "fluxrun_session"
LOGIN_WINDOW_SECONDS = 60
LOGIN_MAX_ATTEMPTS = 10
_login_attempts: dict[str, deque[float]] = defaultdict(deque)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user: User) -> str:
    settings = get_settings()
    raw_token = secrets.token_urlsafe(32)
    db.add(SessionToken(user_id=user.id, token_hash=token_digest(raw_token), expires_at=datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours)))
    return raw_token


def set_session_cookie(response, raw_token: str) -> None:
    settings = get_settings()
    response.set_cookie(SESSION_COOKIE, raw_token, httponly=True, secure=settings.session_cookie_secure, samesite="lax", max_age=settings.session_ttl_hours * 3600, path="/")


def require_same_origin(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if request.headers.get("authorization", "").startswith("Bearer "):
        return
    origin = request.headers.get("origin")
    settings = get_settings()
    if not origin or origin not in settings.cors_origin_list:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin mutation rejected")


def enforce_login_rate_limit(request: Request, email: str) -> None:
    """Bound abusive login attempts in local single-process deployments.

    Production deployments should place this policy in a shared edge or Redis
    limiter before running multiple API replicas.
    """
    client_host = request.client.host if request.client else "unknown"
    from redis import Redis
    from redis.exceptions import RedisError
    try:
        redis = Redis.from_url(get_settings().redis_url, socket_timeout=2, socket_connect_timeout=2)
        script = "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n"
        identifier = hashlib.sha256(f"{client_host}:{email.lower()}".encode()).hexdigest()
        count = redis.eval(script, 1, f"fluxrun:login:{identifier}", LOGIN_WINDOW_SECONDS)
        if count > LOGIN_MAX_ATTEMPTS:
            raise HTTPException(429, "Too many login attempts; try again shortly")
        return
    except RedisError:
        if get_settings().environment != "test":
            raise HTTPException(503, "Authentication rate limiter unavailable; retry shortly")
    key = f"{client_host}:{email.lower()}"
    now = time.monotonic()
    attempts = _login_attempts[key]
    while attempts and attempts[0] <= now - LOGIN_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= LOGIN_MAX_ATTEMPTS:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many login attempts; try again shortly")
    attempts.append(now)


def current_user_from_request(request: Request, db: Session) -> User:
    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        from .tracking_models import ApiKey
        from .domain import utc
        key = db.scalar(select(ApiKey).where(ApiKey.token_hash == token_digest(authorization[7:])))
        if not key or key.revoked_at or utc(key.expires_at) <= datetime.now(UTC):
            raise HTTPException(401, "Invalid, expired or revoked API key")
        user = db.get(User, key.user_id)
        if not user or not user.is_active:
            raise HTTPException(401, "Authentication required")
        request.state.api_key = key
        key.last_used_at = datetime.now(UTC)
        db.flush()
        return user
    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Authentication required")
    session = db.scalar(select(SessionToken).where(SessionToken.token_hash == token_digest(raw_token), SessionToken.revoked_at.is_(None)))
    expires_at = session.expires_at.replace(tzinfo=UTC) if session and session.expires_at.tzinfo is None else (session.expires_at if session else None)
    if not session or not expires_at or expires_at < datetime.now(UTC):
        raise HTTPException(status_code=401, detail="Session expired")
    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user
