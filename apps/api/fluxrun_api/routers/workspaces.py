from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import current_user, mutation_guard
from ..models import AuditEvent, User, Workspace, WorkspaceMembership, WorkspaceRole
from ..schemas import WorkspaceCreate, WorkspaceOut

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Workspace, WorkspaceMembership.role).join(WorkspaceMembership).where(WorkspaceMembership.user_id == user.id, Workspace.archived_at.is_(None)).order_by(Workspace.name)).all()
    return [WorkspaceOut(id=workspace.id, name=workspace.name, slug=workspace.slug, role=role, created_at=workspace.created_at) for workspace, role in rows]


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
def create_workspace(payload: WorkspaceCreate, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db), _: None = Depends(mutation_guard)):
    workspace = Workspace(name=payload.name.strip(), slug=payload.slug, created_by=user.id)
    db.add(workspace)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Workspace slug already exists")
    db.add(WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.owner))
    db.add(AuditEvent(actor_id=user.id, workspace_id=workspace.id, action="workspace.created", resource_type="workspace", resource_id=str(workspace.id)))
    db.commit()
    db.refresh(workspace)
    return WorkspaceOut(id=workspace.id, name=workspace.name, slug=workspace.slug, role=WorkspaceRole.owner, created_at=workspace.created_at)
