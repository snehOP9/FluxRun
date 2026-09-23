from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ..contracts import Compare, Input, Named
from ..db import get_db
from ..deps import current_user, mutation_guard
from ..domain import cursor_page, fingerprint, item_access, project_access, record, redact, remember, replay, serialize
from ..models import User
from ..prompts import render_prompt, validate_prompt
from ..registry_models import RegistryAlias, RegistryItem, RegistryVersion, RunDataset
from ..tracking_models import Artifact, Run

router = APIRouter(prefix="/api/v1", tags=["registry"], dependencies=[Depends(mutation_guard)])
ITEM_FIELDS = "id project_id kind name description created_by created_at archived_at"
VERSION_FIELDS = "id item_id project_id number data digest message source_run_id artifact_id created_by created_at"


class RegistryCreate(Named):
    kind: Literal["model", "prompt", "dataset", "evaluation_dataset"]


class VersionCreate(Input):
    data: dict[str, Any] = Field(default_factory=dict, max_length=30)
    message: str = Field(default="", max_length=1000)
    source_run_id: UUID | None = None
    artifact_id: UUID | None = None


class AliasMove(Input):
    version_id: UUID
    expected_version_id: UUID | None = None


class Render(Input):
    variables: dict[str, Any] = Field(max_length=100)


class DatasetLink(Input):
    version_id: UUID
    role: Literal["training", "validation", "test", "evaluation", "retrieval"]


@router.get("/projects/{project_id}/registry")
def items(project_id: UUID, request: Request, kind: str = Query(pattern="^(model|prompt|dataset|evaluation_dataset)$"), q: str = "", cursor: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project_access(db, request, user, project_id)
    rows, page = cursor_page(db, select(RegistryItem).where(RegistryItem.project_id == project_id, RegistryItem.kind == kind, RegistryItem.archived_at.is_(None), RegistryItem.name.ilike(f"%{q[:120]}%")), RegistryItem, cursor)
    counts = dict(db.execute(select(RegistryVersion.item_id, func.count()).where(RegistryVersion.item_id.in_([i.id for i in rows])).group_by(RegistryVersion.item_id)).all())
    return {"items": [{**serialize(i, ITEM_FIELDS), "versions": counts.get(i.id, 0)} for i in rows], "page": page}


@router.post("/projects/{project_id}/registry", status_code=201)
def create(project_id: UUID, payload: RegistryCreate, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = project_access(db, request, user, project_id, "registry:write")
    item = RegistryItem(project_id=project_id, created_by=user.id, **payload.model_dump())
    db.add(item); db.flush(); record(db, user, project, f"{payload.kind}.created", item); db.commit()
    return serialize(item, ITEM_FIELDS)


@router.get("/registry/{identity}")
def detail(identity: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item, _ = item_access(db, request, user, RegistryItem, identity)
    versions = list(db.scalars(select(RegistryVersion).where(RegistryVersion.item_id == identity).order_by(RegistryVersion.number.desc()).limit(100)))
    aliases = {a.name: str(a.version_id) for a in db.scalars(select(RegistryAlias).where(RegistryAlias.item_id == identity))}
    return {**serialize(item, ITEM_FIELDS), "versions": [serialize(v, VERSION_FIELDS) for v in versions], "aliases": aliases}


@router.post("/registry/{identity}/versions", status_code=201)
def version(identity: UUID, payload: VersionCreate, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item, project = item_access(db, request, user, RegistryItem, identity, "registry:write", lock=True)
    key, prior = replay(db, request, project.id, payload.model_dump())
    if prior: return prior
    if item.archived_at: raise HTTPException(409, "Registry item is archived")
    data = payload.data.copy()
    source_run_id = payload.source_run_id
    if item.kind == "prompt":
        data["variables"] = validate_prompt(data)
    if item.kind == "model":
        if not payload.artifact_id: raise HTTPException(422, "Register a model from a completed run artifact")
        artifact, _ = item_access(db, request, user, Artifact, payload.artifact_id)
        if artifact.project_id != item.project_id or artifact.status != "complete": raise HTTPException(422, "Artifact must be complete and in this project")
        if source_run_id and source_run_id != artifact.run_id: raise HTTPException(422, "Source run must own the artifact")
        source_run_id = artifact.run_id
        data.update({"sha256": artifact.sha256, "size": artifact.size, "path": artifact.path})
    if source_run_id:
        source, _ = item_access(db, request, user, Run, source_run_id)
        if source.project_id != item.project_id: raise HTTPException(422, "Source must belong to the same project")
    if item.kind == "dataset":
        if not isinstance(data.get("fingerprint"), str) or len(data["fingerprint"]) < 8: raise HTTPException(422, "Dataset requires a stable content fingerprint")
        source_uri = data.get("source_uri", "")
        if "@" in source_uri or "?" in source_uri: raise HTTPException(422, "Source URI must not contain credentials or query secrets")
    if item.kind == "evaluation_dataset":
        from ..evaluation import validate_cases
        data = validate_cases(db, request, user, item.project_id, data)
    next_number = (db.scalar(select(func.max(RegistryVersion.number)).where(RegistryVersion.item_id == item.id)) or 0) + 1
    digest = fingerprint(data)
    cases = data.pop("cases", None) if item.kind == "evaluation_dataset" else None
    if cases is not None: data["case_count"] = len(cases)
    row = RegistryVersion(item_id=identity, project_id=project.id, number=next_number, data=data, digest=digest, message=payload.message, source_run_id=source_run_id, artifact_id=payload.artifact_id, created_by=user.id)
    db.add(row); db.flush()
    if cases is not None:
        from ..observability_models import EvaluationCase
        for position, case in enumerate(cases):
            db.add(EvaluationCase(version_id=row.id, position=position, data=case))
    record(db, user, project, f"{item.kind}.version.created", row, {"number": next_number})
    response = serialize(row, VERSION_FIELDS)
    remember(db, project.id, key, payload.model_dump(), response)
    db.commit()
    return response


@router.put("/registry/{identity}/aliases/{name}")
def alias(identity: UUID, name: str, payload: AliasMove, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    import re
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name): raise HTTPException(422, "Invalid alias name")
    item, project = item_access(db, request, user, RegistryItem, identity, "registry:write", lock=True)
    target = db.get(RegistryVersion, payload.version_id)
    if not target or target.item_id != identity: raise HTTPException(404, "Version does not belong to this registry item")
    old = db.get(RegistryAlias, (identity, name))
    if (old.version_id if old else None) != payload.expected_version_id: raise HTTPException(409, "Alias changed since this page loaded. Refresh and review before moving it.")
    previous = str(old.version_id) if old else None
    if old: old.version_id, old.changed_by = payload.version_id, user.id
    else: db.add(RegistryAlias(item_id=identity, name=name, version_id=payload.version_id, changed_by=user.id))
    record(db, user, project, f"{item.kind}.alias.changed", item, {"alias": name, "previous": previous, "target": str(target.id)})
    db.commit()
    return {"alias": name, "version_id": target.id}


@router.post("/registry/{identity}/archive", status_code=204)
def archive(identity: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item, project = item_access(db, request, user, RegistryItem, identity, "registry:write", lock=True)
    item.archived_at = datetime.now(UTC); record(db, user, project, "registry.archived", item); db.commit()


@router.post("/versions/{identity}/render")
def render(identity: UUID, payload: Render, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    version, _ = item_access(db, request, user, RegistryVersion, identity)
    item = db.get(RegistryItem, version.item_id)
    if item.kind != "prompt": raise HTTPException(422, "Only prompts can be rendered")
    return {"rendered": render_prompt(version.data, payload.variables)}


@router.get("/versions/{identity}/lineage")
def lineage(identity: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    version, _ = item_access(db, request, user, RegistryVersion, identity)
    linked = list(db.scalars(select(Run).join(RunDataset, RunDataset.run_id == Run.id).where(RunDataset.version_id == identity).limit(100)))
    return {"version": serialize(version, VERSION_FIELDS), "runs": [serialize(r, "id name experiment_id status source") for r in linked]}


@router.post("/versions:compare")
def compare(payload: Compare, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    versions = [item_access(db, request, user, RegistryVersion, i)[0] for i in payload.ids]
    if len({v.item_id for v in versions}) != 1: raise HTTPException(422, "Compare versions of the same item")
    return {"versions": [serialize(v, VERSION_FIELDS) for v in versions]}


@router.post("/runs/{identity}/datasets", status_code=204)
def link_dataset(identity: UUID, payload: DatasetLink, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    run, _ = item_access(db, request, user, Run, identity, "tracking:write", lock=True)
    version, _ = item_access(db, request, user, RegistryVersion, payload.version_id)
    if version.project_id != run.project_id or db.get(RegistryItem, version.item_id).kind != "dataset": raise HTTPException(422, "Link a dataset version from the same project")
    if not db.get(RunDataset, (run.id, version.id, payload.role)): db.add(RunDataset(run_id=run.id, version_id=version.id, role=payload.role))
    db.commit()


@router.get("/runs/{identity}/datasets")
def run_datasets(identity: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item_access(db, request, user, Run, identity)
    return [{"role": link.role, "version": serialize(version, VERSION_FIELDS)} for link, version in db.execute(select(RunDataset, RegistryVersion).join(RegistryVersion, RunDataset.version_id == RegistryVersion.id).where(RunDataset.run_id == identity).limit(100))]
