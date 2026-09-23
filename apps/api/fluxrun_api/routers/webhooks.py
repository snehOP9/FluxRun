import secrets
from uuid import UUID
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..config import get_settings
from ..contracts import Input
from ..db import get_db
from ..deps import current_user, mutation_guard
from ..domain import project_access, record, serialize
from ..models import User
from ..webhook_models import Webhook, WebhookDelivery
from ..webhooks import public_address
from .administration import admin

router = APIRouter(prefix="/api/v1", tags=["webhooks"], dependencies=[Depends(mutation_guard)])


class Create(Input):
    name: str = Field(min_length=2, max_length=120)
    url: str = Field(max_length=2000)
    events: list[str] = Field(min_length=1, max_length=20)


@router.get("/projects/{project_id}/webhooks")
def hooks(project_id: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = project_access(db, request, user, project_id)
    admin(db, project.workspace_id, user)
    return [serialize(h, "id name url events enabled created_at") for h in db.scalars(select(Webhook).where(Webhook.project_id == project_id).limit(100))]


@router.post("/projects/{project_id}/webhooks", status_code=201)
def create(project_id: UUID, payload: Create, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = project_access(db, request, user, project_id)
    admin(db, project.workspace_id, user)
    public_address(payload.url)
    secret = secrets.token_urlsafe(32)
    try: encrypted = Fernet(get_settings().encryption_key.encode()).encrypt(secret.encode()).decode()
    except (ValueError, TypeError): raise HTTPException(503, "Operator must configure ENCRYPTION_KEY before webhooks can be created")
    hook = Webhook(project_id=project_id, workspace_id=project.workspace_id, created_by=user.id, encrypted_secret=encrypted, **payload.model_dump())
    db.add(hook); db.flush(); record(db, user, project, "webhook.created", hook); db.commit()
    return {**serialize(hook, "id name url events enabled"), "signing_secret": secret}


@router.post("/projects/{project_id}/webhooks/{identity}/disable", status_code=204)
def disable(project_id: UUID, identity: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = project_access(db, request, user, project_id)
    admin(db, project.workspace_id, user)
    hook = db.get(Webhook, identity)
    if not hook or hook.project_id != project_id: raise HTTPException(404, "Webhook not found")
    hook.enabled = False; record(db, user, project, "webhook.disabled", hook); db.commit()


@router.get("/projects/{project_id}/webhooks/{identity}/deliveries")
def deliveries(project_id: UUID, identity: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = project_access(db, request, user, project_id)
    admin(db, project.workspace_id, user)
    hook = db.get(Webhook, identity)
    if not hook or hook.project_id != project_id: raise HTTPException(404, "Webhook not found")
    return [serialize(d, "id event_id attempts status response_code next_attempt_at created_at") for d in db.scalars(select(WebhookDelivery).where(WebhookDelivery.webhook_id == identity).order_by(WebhookDelivery.id.desc()).limit(100))]
