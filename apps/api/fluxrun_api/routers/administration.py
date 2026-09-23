from datetime import UTC, datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import EmailStr, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from redis import Redis
from ..config import get_settings
from ..contracts import Input
from ..db import get_db
from ..deps import current_user, membership_for, mutation_guard
from ..domain import project_access, serialize
from ..models import AuditEvent, Project, User, WorkspaceMembership, WorkspaceRole
from ..storage import s3
from ..tracking_models import Experiment, Run

router = APIRouter(tags=["administration"])


class MemberInput(Input):
    email: EmailStr
    role: WorkspaceRole


class PrivacyInput(Input):
    store_trace_content: bool = True
    trace_retention_days: int = Field(default=30, ge=1, le=3650)
    trace_preview_chars: int = Field(default=2000, ge=0, le=16000)


def admin(db, workspace_id, user):
    membership = membership_for(db, workspace_id, user.id)
    if membership.role not in {WorkspaceRole.owner, WorkspaceRole.admin}:
        raise HTTPException(403, "Workspace administrator permission required")
    return membership


@router.get("/readyz")
def ready(db: Session = Depends(get_db)):
    status = {}
    for name, check in {"database": lambda: db.execute(text("SELECT 1")), "redis": lambda: Redis.from_url(get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2).ping(), "storage": lambda: s3().head_bucket(Bucket=get_settings().s3_bucket)}.items():
        try: check(); status[name] = "ok"
        except Exception: status[name] = "unavailable"
    if any(v != "ok" for v in status.values()):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content={"status": "not_ready", "services": status})
    return {"status": "ready", "services": status}


@router.get("/api/v1/meta")
def meta(user: User = Depends(current_user)):
    return {"version": "0.4.0", "server_time": datetime.now(UTC), "limits": {"metric_batch": 2000, "artifact_bytes": get_settings().max_artifact_bytes}}


@router.get("/api/v1/projects/{project_id}/summary")
def summary(project_id: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = project_access(db, request, user, project_id)
    counts = dict(db.execute(select(Run.status, func.count()).where(Run.project_id == project_id, Run.archived_at.is_(None)).group_by(Run.status)).all())
    return {"project": {**serialize(project, "id name slug description settings workspace_id"), "role": membership_for(db, project.workspace_id, user.id).role}, "runs": counts, "experiments": db.scalar(select(func.count()).select_from(Experiment).where(Experiment.project_id == project_id, Experiment.archived_at.is_(None)))}


@router.get("/api/v1/workspaces/{workspace_id}/members")
def members(workspace_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    membership_for(db, workspace_id, user.id)
    return [{"id": str(m.id), "user_id": str(u.id), "email": u.email, "name": u.display_name, "role": m.role} for m, u in db.execute(select(WorkspaceMembership, User).join(User, WorkspaceMembership.user_id == User.id).where(WorkspaceMembership.workspace_id == workspace_id).limit(100))]


@router.post("/api/v1/workspaces/{workspace_id}/members", dependencies=[Depends(mutation_guard)])
def add_member(workspace_id: UUID, payload: MemberInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    admin(db, workspace_id, user)
    if payload.role == WorkspaceRole.owner:
        raise HTTPException(422, "Ownership transfer requires a separate operator workflow")
    target = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not target: raise HTTPException(404, "User must register before being added")
    existing = db.scalar(select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id, WorkspaceMembership.user_id == target.id).with_for_update())
    if existing and (existing.role == WorkspaceRole.owner or existing.user_id == user.id):
        raise HTTPException(409, "You cannot change your own role or the owner's role")
    if existing: existing.role = payload.role
    else: db.add(WorkspaceMembership(workspace_id=workspace_id, user_id=target.id, role=payload.role))
    db.add(AuditEvent(actor_id=user.id, workspace_id=workspace_id, action="membership.changed", resource_type="user", resource_id=str(target.id), detail={"role": payload.role.value}))
    db.commit()
    return {"status": "saved"}


@router.delete("/api/v1/workspaces/{workspace_id}/members/{identity}", status_code=204, dependencies=[Depends(mutation_guard)])
def remove_member(workspace_id: UUID, identity: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    admin(db, workspace_id, user)
    member = db.get(WorkspaceMembership, identity)
    if not member or member.workspace_id != workspace_id: raise HTTPException(404, "Membership not found")
    if member.role == WorkspaceRole.owner or member.user_id == user.id: raise HTTPException(409, "Cannot remove owner or yourself")
    db.add(AuditEvent(actor_id=user.id, workspace_id=workspace_id, action="membership.removed", resource_type="user", resource_id=str(member.user_id)))
    db.delete(member); db.commit()


@router.get("/api/v1/workspaces/{workspace_id}/activity")
def activity(workspace_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    membership_for(db, workspace_id, user.id)
    return [serialize(e, "id actor_id action resource_type resource_id detail created_at") for e in db.scalars(select(AuditEvent).where(AuditEvent.workspace_id == workspace_id).order_by(AuditEvent.created_at.desc()).limit(100))]


@router.patch("/api/v1/projects/{project_id}/privacy", dependencies=[Depends(mutation_guard)])
def privacy(project_id: UUID, payload: PrivacyInput, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = project_access(db, request, user, project_id)
    admin(db, project.workspace_id, user)
    project.settings = {**project.settings, **payload.model_dump()}
    db.add(AuditEvent(actor_id=user.id, workspace_id=project.workspace_id, action="privacy.changed", resource_type="project", resource_id=str(project.id), detail=payload.model_dump()))
    db.commit()
    return project.settings
