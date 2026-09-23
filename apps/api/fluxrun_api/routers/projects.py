from datetime import UTC, datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import current_user, membership_for, mutation_guard, require_editor
from ..models import AuditEvent, Project, User
from ..schemas import ProjectCreate, ProjectOut, ProjectUpdate

router = APIRouter(tags=["projects"])


@router.get("/api/v1/workspaces/{workspace_id}/projects", response_model=list[ProjectOut])
def list_projects(workspace_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    membership_for(db, workspace_id, user.id)
    return list(db.scalars(select(Project).where(Project.workspace_id == workspace_id, Project.archived_at.is_(None)).order_by(Project.name)))


@router.post("/api/v1/workspaces/{workspace_id}/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(workspace_id: UUID, payload: ProjectCreate, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db), _: None = Depends(mutation_guard)):
    require_editor(membership_for(db, workspace_id, user.id))
    project = Project(workspace_id=workspace_id, name=payload.name.strip(), slug=payload.slug, description=payload.description, created_by=user.id)
    db.add(project)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Project slug already exists in this workspace")
    db.add(AuditEvent(actor_id=user.id, workspace_id=workspace_id, action="project.created", resource_type="project", resource_id=str(project.id)))
    db.commit()
    db.refresh(project)
    return project


@router.patch("/api/v1/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: UUID, payload: ProjectUpdate, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db), _: None = Depends(mutation_guard)):
    project = db.get(Project, project_id)
    if not project or project.archived_at:
        raise HTTPException(status_code=404, detail="Project not found")
    require_editor(membership_for(db, project.workspace_id, user.id))
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value.strip() if field == "name" and value else value)
    db.add(AuditEvent(actor_id=user.id, workspace_id=project.workspace_id, action="project.updated", resource_type="project", resource_id=str(project.id)))
    db.commit()
    db.refresh(project)
    return project


@router.post("/api/v1/projects/{project_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
def archive_project(project_id: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db), _: None = Depends(mutation_guard)):
    project = db.get(Project, project_id)
    if not project or project.archived_at:
        raise HTTPException(status_code=404, detail="Project not found")
    require_editor(membership_for(db, project.workspace_id, user.id))
    project.archived_at = datetime.now(UTC)
    db.add(AuditEvent(actor_id=user.id, workspace_id=project.workspace_id, action="project.archived", resource_type="project", resource_id=str(project.id)))
    db.commit()
