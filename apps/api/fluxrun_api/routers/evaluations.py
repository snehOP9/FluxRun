from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..config import get_settings
from ..contracts import Compare, Input
from ..db import get_db
from ..deps import current_user, mutation_guard
from ..domain import cursor_page, item_access, project_access, record, remember, replay, serialize
from ..evaluation import SCORERS, validate_scorers
from ..models import User
from ..observability_models import Evaluation, EvaluationCase, EvaluationResult
from ..registry_models import RegistryItem, RegistryVersion

router = APIRouter(prefix="/api/v1", tags=["evaluations"], dependencies=[Depends(mutation_guard)])
FIELDS = "id project_id name dataset_version_id target_version_id target_type scorers status completed total aggregates error cancel_requested started_at ended_at created_at"


class EvaluationCreate(Input):
    name: str = Field(min_length=2, max_length=120)
    dataset_version_id: UUID
    target_version_id: UUID | None = None
    target_type: Literal["prompt_render", "recorded_outputs"]
    scorers: list[dict] = Field(min_length=1, max_length=8)


@router.get("/scorers")
def scorers(user: User = Depends(current_user)):
    return [{"name": name, "version": 1} for name in sorted(SCORERS)]


@router.get("/versions/{identity}/cases")
def cases(identity: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item_access(db, request, user, RegistryVersion, identity)
    return [serialize(c, "id version_id position data") for c in db.scalars(select(EvaluationCase).where(EvaluationCase.version_id == identity).order_by(EvaluationCase.position).limit(1000))]


@router.post("/projects/{project_id}/evaluations", status_code=202)
def create(project_id: UUID, payload: EvaluationCreate, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = project_access(db, request, user, project_id, "registry:write")
    version, _ = item_access(db, request, user, RegistryVersion, payload.dataset_version_id, lock=True)
    key, prior = replay(db, request, project_id, payload.model_dump())
    if prior: return prior
    if version.project_id != project_id or db.get(RegistryItem, version.item_id).kind != "evaluation_dataset": raise HTTPException(422, "Select an evaluation dataset version in this project")
    if payload.target_type == "prompt_render":
        if not payload.target_version_id: raise HTTPException(422, "Prompt rendering requires a target prompt version")
        target, _ = item_access(db, request, user, RegistryVersion, payload.target_version_id)
        if target.project_id != project_id or db.get(RegistryItem, target.item_id).kind != "prompt": raise HTTPException(422, "Select a prompt version in this project")
    elif payload.target_version_id: raise HTTPException(422, "Recorded outputs do not use a prompt target")
    scorers = validate_scorers(payload.scorers)
    try: Redis.from_url(get_settings().redis_url, socket_timeout=2).ping()
    except RedisError: raise HTTPException(503, "Queue is unavailable; evaluation was not submitted")
    evaluation = Evaluation(project_id=project_id, created_by=user.id, total=version.data["case_count"], **{**payload.model_dump(), "scorers": scorers})
    db.add(evaluation); db.flush(); record(db, user, project, "evaluation.submitted", evaluation)
    response = serialize(evaluation, FIELDS)
    remember(db, project_id, key, payload.model_dump(), response); db.commit()
    from fluxrun_worker.tasks import execute_evaluation
    try: execute_evaluation.delay(str(evaluation.id))
    except Exception:
        # Durable queued row is picked up by the dispatcher's next scan.
        pass
    return response


@router.get("/projects/{project_id}/evaluations")
def evaluations(project_id: UUID, request: Request, cursor: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project_access(db, request, user, project_id)
    items, page = cursor_page(db, select(Evaluation).where(Evaluation.project_id == project_id), Evaluation, cursor)
    return {"items": [serialize(e, FIELDS) for e in items], "page": page}


@router.get("/evaluations/{identity}")
def detail(identity: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item, _ = item_access(db, request, user, Evaluation, identity)
    results = list(db.scalars(select(EvaluationResult).where(EvaluationResult.evaluation_id == identity).order_by(EvaluationResult.created_at).limit(1000)))
    return {**serialize(item, FIELDS), "results": [serialize(r, "id case_id input expected actual scores status error") for r in results]}


@router.post("/evaluations/{identity}/cancel")
def cancel(identity: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item, _ = item_access(db, request, user, Evaluation, identity, "registry:write", lock=True)
    if item.status not in {"queued", "running"}: raise HTTPException(409, "Evaluation has already finished")
    item.cancel_requested = True; db.commit()
    return {"status": "cancellation_requested"}


@router.post("/evaluations:compare")
def compare(payload: Compare, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = [item_access(db, request, user, Evaluation, i)[0] for i in payload.ids]
    if len({e.project_id for e in items}) != 1: raise HTTPException(422, "Compare within one project")
    return {"evaluations": [serialize(e, FIELDS) for e in items], "same_dataset": len({e.dataset_version_id for e in items}) == 1}
