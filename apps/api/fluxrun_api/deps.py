from uuid import UUID
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import get_db
from .models import User, WorkspaceMembership, WorkspaceRole
from .security import current_user_from_request, require_same_origin


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = current_user_from_request(request, db)
    if getattr(request.state, "api_key", None) and not any(part in request.url.path for part in ("/experiments", "/runs", "/artifacts", "/registry", "/versions", "/models", "/datasets", "/prompts", "/traces", "/evaluations", "/meta", "/auth/me")):
        raise HTTPException(403, "SDK keys cannot administer workspaces or account settings")
    return user


def mutation_guard(request: Request) -> None:
    require_same_origin(request)


def membership_for(db: Session, workspace_id: UUID, user_id: UUID) -> WorkspaceMembership:
    membership = db.scalar(select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id, WorkspaceMembership.user_id == user_id))
    if not membership:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return membership


def require_editor(membership: WorkspaceMembership) -> None:
    if membership.role not in {WorkspaceRole.owner, WorkspaceRole.admin, WorkspaceRole.member, WorkspaceRole.editor}:
        raise HTTPException(status_code=403, detail="Workspace editor permission required")
