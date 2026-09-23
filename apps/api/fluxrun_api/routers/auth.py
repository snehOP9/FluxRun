from datetime import UTC, datetime
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import current_user, mutation_guard
from ..models import SessionToken, User
from ..schemas import LoginIn, UserOut
from ..contracts import Input
from ..config import get_settings
from pydantic import EmailStr, Field
from ..security import hash_password
from ..security import SESSION_COOKIE, create_session, enforce_login_rate_limit, set_session_cookie, token_digest, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class Signup(Input):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    display_name: str = Field(min_length=2, max_length=120)


@router.post("/signup", response_model=UserOut, status_code=201)
def signup(payload: Signup, request: Request, response: Response, db: Session = Depends(get_db)):
    mutation_guard(request)
    if not get_settings().signup_enabled:
        raise HTTPException(403, "Public registration is disabled by the operator")
    enforce_login_rate_limit(request, payload.email)
    user = User(email=payload.email.lower(), display_name=payload.display_name, password_hash=hash_password(payload.password))
    db.add(user); db.flush()
    set_session_cookie(response, create_session(db, user)); db.commit()
    return user


@router.post("/login", response_model=UserOut)
def login(payload: LoginIn, response: Response, request: Request, db: Session = Depends(get_db)):
    mutation_guard(request)
    enforce_login_rate_limit(request, payload.email)
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    set_session_cookie(response, create_session(db, user))
    db.commit()
    return user


@router.post("/logout", status_code=204)
def logout(response: Response, request: Request, db: Session = Depends(get_db), _: None = Depends(mutation_guard)):
    raw_token = request.cookies.get(SESSION_COOKIE)
    if raw_token:
        session = db.scalar(select(SessionToken).where(SessionToken.token_hash == token_digest(raw_token)))
        if session:
            session.revoked_at = datetime.now(UTC)
            db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
