from datetime import UTC, datetime, timedelta
import json
import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..contracts import Compare, Entity, KeyCreate, MetricBatch, Named, Page, Params, RunCreate, RunFinish, Tags
from ..db import get_db
from ..deps import current_user, mutation_guard
from ..domain import cursor_page, item_access, project_access, record, redact, remember, replay, serialize, utc
from ..models import User
from ..security import token_digest
from ..tracking_models import ApiKey, Experiment, MetricPoint, MetricSummary, Run, RunParam, RunTag

router = APIRouter(prefix="/api/v1", tags=["tracking"], dependencies=[Depends(mutation_guard)])
RUN_FIELDS = "id experiment_id project_id parent_run_id name status created_by started_at ended_at archived_at source error created_at"
EXP_FIELDS = "id project_id name description created_by created_at archived_at"


def run_view(db, run, detail=False):
    result = serialize(run, RUN_FIELDS)
    result["metrics"] = {m.key: m.latest for m in db.scalars(select(MetricSummary).where(MetricSummary.run_id == run.id))}
    if detail:
        result["params"] = {p.key: p.value for p in db.scalars(select(RunParam).where(RunParam.run_id == run.id))}
        result["tags"] = {p.key: p.value for p in db.scalars(select(RunTag).where(RunTag.run_id == run.id))}
    return result


def active_run(run):
    if run.status not in {"running", "queued"} or run.archived_at:
        raise HTTPException(409, "Run is terminal or archived; its measurements are immutable")


@router.get("/projects/{project_id}/keys")
def keys(project_id: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project_access(db, request, user, project_id)
    return [serialize(k, "id name prefix scopes expires_at last_used_at revoked_at created_at") for k in db.scalars(select(ApiKey).where(ApiKey.project_id == project_id, ApiKey.user_id == user.id).limit(100))]


@router.post("/projects/{project_id}/keys", status_code=201)
def create_key(project_id: UUID, payload: KeyCreate, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = project_access(db, request, user, project_id, "tracking:write")
    secret = "fr_live_" + secrets.token_urlsafe(32)
    key = ApiKey(project_id=project_id, user_id=user.id, name=payload.name, prefix=secret[:16], token_hash=token_digest(secret), scopes=payload.scopes, expires_at=datetime.now(UTC) + timedelta(days=payload.expires_days))
    db.add(key); db.flush()
    record(db, user, project, "api_key.created", key)
    db.commit()
    return {**serialize(key, "id name prefix scopes expires_at"), "secret": secret}


@router.post("/projects/{project_id}/keys/{key_id}/revoke", status_code=204)
def revoke_key(project_id: UUID, key_id: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = project_access(db, request, user, project_id, "tracking:write")
    key = db.get(ApiKey, key_id)
    if not key or key.project_id != project_id or key.user_id != user.id:
        raise HTTPException(404, "API key not found")
    key.revoked_at = datetime.now(UTC)
    record(db, user, project, "api_key.revoked", key)
    db.commit()


@router.get("/projects/{project_id}/experiments", response_model=Page)
def experiments(project_id: UUID, request: Request, q: str = "", archived: bool = False, cursor: str | None = None, limit: int = Query(50, ge=1, le=100), user: User = Depends(current_user), db: Session = Depends(get_db)):
    project_access(db, request, user, project_id)
    query = select(Experiment).where(Experiment.project_id == project_id, Experiment.name.ilike(f"%{q[:120]}%"))
    if not archived:
        query = query.where(Experiment.archived_at.is_(None))
    items, page = cursor_page(db, query, Experiment, cursor, limit)
    counts = dict(db.execute(select(Run.experiment_id, func.count()).where(Run.experiment_id.in_([e.id for e in items])).group_by(Run.experiment_id)).all()) if items else {}
    return {"items": [{**serialize(e, EXP_FIELDS), "run_count": counts.get(e.id, 0)} for e in items], "page": page}


@router.post("/projects/{project_id}/experiments", response_model=Entity, status_code=201)
def create_experiment(project_id: UUID, payload: Named, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = project_access(db, request, user, project_id, "tracking:write")
    existing = db.scalar(select(Experiment).where(Experiment.project_id == project_id, Experiment.name == payload.name))
    if existing:
        if existing.archived_at:
            raise HTTPException(409, "An archived experiment has this name")
        return serialize(existing, EXP_FIELDS)
    experiment = Experiment(project_id=project_id, created_by=user.id, **payload.model_dump())
    db.add(experiment); db.flush()
    record(db, user, project, "experiment.created", experiment)
    db.commit()
    return serialize(experiment, EXP_FIELDS)


@router.get("/experiments/{identity}", response_model=Entity)
def experiment(identity: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item, _ = item_access(db, request, user, Experiment, identity)
    return serialize(item, EXP_FIELDS)


@router.patch("/experiments/{identity}", response_model=Entity)
def update_experiment(identity: UUID, payload: Named, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item, _ = item_access(db, request, user, Experiment, identity, "tracking:write")
    item.name, item.description = payload.name, payload.description
    db.commit()
    return serialize(item, EXP_FIELDS)


@router.post("/experiments/{identity}/archive", status_code=204)
def archive_experiment(identity: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item, project = item_access(db, request, user, Experiment, identity, "tracking:write")
    item.archived_at = datetime.now(UTC)
    record(db, user, project, "experiment.archived", item); db.commit()


@router.post("/experiments/{identity}/runs", response_model=Entity, status_code=201)
def create_run(identity: UUID, payload: RunCreate, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    experiment, project = item_access(db, request, user, Experiment, identity, "tracking:write", lock=True)
    key, prior = replay(db, request, project.id, payload.model_dump())
    if prior:
        return prior
    if experiment.archived_at:
        raise HTTPException(409, "Cannot create a run in an archived experiment")
    if payload.parent_run_id:
        parent, _ = item_access(db, request, user, Run, payload.parent_run_id)
        if parent.experiment_id != identity:
            raise HTTPException(422, "Parent run must belong to the same experiment")
    run = Run(experiment_id=identity, project_id=project.id, name=payload.name, parent_run_id=payload.parent_run_id, source=redact(payload.source), created_by=user.id)
    db.add(run); db.flush()
    for name, value in payload.tags.items():
        if not name or len(name) > 128 or len(value) > 1024:
            raise HTTPException(422, "Tag key or value is too long")
        db.add(RunTag(run_id=run.id, key=name, value=value))
    record(db, user, project, "run.created", run)
    response = run_view(db, run, True)
    remember(db, project.id, key, payload.model_dump(), response)
    db.commit()
    return response


@router.get("/projects/{project_id}/runs", response_model=Page)
def list_runs(project_id: UUID, request: Request, experiment_id: UUID | None = None, q: str = "", status: str | None = None, archived: bool = False, creator: UUID | None = None, parent: UUID | None = None, tag_key: str | None = None, tag_value: str | None = None, param_key: str | None = None, param_value: str | None = None, metric_key: str | None = None, metric_min: float | None = None, metric_max: float | None = None, after: datetime | None = None, before: datetime | None = None, cursor: str | None = None, limit: int = Query(50, ge=1, le=100), user: User = Depends(current_user), db: Session = Depends(get_db)):
    project_access(db, request, user, project_id)
    query = select(Run).where(Run.project_id == project_id)
    if not archived: query = query.where(Run.archived_at.is_(None))
    if experiment_id: query = query.where(Run.experiment_id == experiment_id)
    if q: query = query.where(Run.name.ilike(f"%{q[:120]}%"))
    if status: query = query.where(Run.status == status)
    if creator: query = query.where(Run.created_by == creator)
    if parent: query = query.where(Run.parent_run_id == parent)
    if after: query = query.where(Run.started_at >= after)
    if before: query = query.where(Run.started_at <= before)
    if tag_key: query = query.where(Run.id.in_(select(RunTag.run_id).where(RunTag.key == tag_key, RunTag.value == tag_value)))
    if param_key: query = query.where(Run.id.in_(select(RunParam.run_id).where(RunParam.key == param_key, RunParam.value.as_string() == param_value)))
    if metric_key:
        metrics = select(MetricSummary.run_id).where(MetricSummary.key == metric_key)
        if metric_min is not None: metrics = metrics.where(MetricSummary.latest >= metric_min)
        if metric_max is not None: metrics = metrics.where(MetricSummary.latest <= metric_max)
        query = query.where(Run.id.in_(metrics))
    items, page = cursor_page(db, query, Run, cursor, limit)
    summaries = {}
    for metric in db.scalars(select(MetricSummary).where(MetricSummary.run_id.in_([r.id for r in items]))):
        summaries.setdefault(metric.run_id, {})[metric.key] = metric.latest
    return {"items": [{**serialize(r, RUN_FIELDS), "metrics": summaries.get(r.id, {})} for r in items], "page": page}


@router.get("/runs/{identity}", response_model=Entity)
def get_run(identity: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    run, _ = item_access(db, request, user, Run, identity)
    return run_view(db, run, True)


@router.post("/runs/{identity}/finish", response_model=Entity)
def finish(identity: UUID, payload: RunFinish, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    run, project = item_access(db, request, user, Run, identity, "tracking:write", lock=True)
    if run.status == payload.status:
        return run_view(db, run, True)
    active_run(run)
    run.status, run.ended_at, run.error = payload.status, datetime.now(UTC), redact(payload.error)
    record(db, user, project, "run.finished", run, {"status": run.status})
    db.commit()
    return run_view(db, run, True)


@router.post("/runs/{identity}/archive", status_code=204)
def archive_run(identity: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    run, project = item_access(db, request, user, Run, identity, "tracking:write", lock=True)
    if run.status in {"running", "queued"}:
        raise HTTPException(409, "Finish or cancel this run before archiving")
    run.archived_at = datetime.now(UTC)
    record(db, user, project, "run.archived", run); db.commit()


@router.post("/runs/{identity}/params:log", status_code=204)
def params(identity: UUID, payload: Params, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    run, _ = item_access(db, request, user, Run, identity, "tracking:write", lock=True)
    for key, value in payload.params.items():
        if not key or len(key) > 128 or len(json.dumps(value)) > 8192:
            raise HTTPException(422, "Parameter key/value exceeds allowed size")
        existing = db.get(RunParam, (run.id, key))
        if existing and existing.value != value:
            raise HTTPException(409, f"Parameter {key} is immutable")
        if not existing:
            active_run(run)
            db.add(RunParam(run_id=run.id, key=key, value=value))
    db.commit()


@router.post("/runs/{identity}/tags:upsert", status_code=204)
def tags(identity: UUID, payload: Tags, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    run, _ = item_access(db, request, user, Run, identity, "tracking:write", lock=True)
    for key, value in payload.tags.items():
        if not key or len(key) > 128 or len(value) > 1024:
            raise HTTPException(422, "Tag key/value exceeds allowed size")
        existing = db.get(RunTag, (run.id, key))
        if existing: existing.value = value
        else: db.add(RunTag(run_id=run.id, key=key, value=value))
    db.commit()


@router.post("/runs/{identity}/metrics:log-batch")
def log_metrics(identity: UUID, payload: MetricBatch, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    run, _ = item_access(db, request, user, Run, identity, "tracking:write", lock=True)
    ids = [p.id for p in payload.points]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "Duplicate point IDs in batch")
    existing = {p.id: p for p in db.scalars(select(MetricPoint).where(MetricPoint.run_id == run.id, MetricPoint.id.in_(ids)))}
    summaries = {m.key: m for m in db.scalars(select(MetricSummary).where(MetricSummary.run_id == run.id))}
    inserted = 0
    for point in payload.points:
        old = existing.get(point.id)
        if old:
            if (old.key, old.value, old.step, utc(old.timestamp)) != (point.key, point.value, point.step, point.timestamp):
                raise HTTPException(409, "Point ID reused with different content")
            continue
        active_run(run)
        db.add(MetricPoint(run_id=run.id, **point.model_dump()))
        summary = summaries.get(point.key)
        if not summary:
            summary = MetricSummary(run_id=run.id, key=point.key, latest=point.value, minimum=point.value, maximum=point.value, step=point.step, timestamp=point.timestamp)
            summaries[point.key] = summary; db.add(summary)
        else:
            summary.minimum, summary.maximum = min(summary.minimum, point.value), max(summary.maximum, point.value)
            if (point.step, point.timestamp) >= (summary.step, utc(summary.timestamp)):
                summary.latest, summary.step, summary.timestamp = point.value, point.step, point.timestamp
        inserted += 1
    db.commit()
    return {"accepted": inserted, "duplicates": len(existing)}


@router.get("/runs/{identity}/metrics")
def metrics(identity: UUID, request: Request, key: str = Query(min_length=1, max_length=128), limit: int = Query(1000, ge=2, le=10000), user: User = Depends(current_user), db: Session = Depends(get_db)):
    run, _ = item_access(db, request, user, Run, identity)
    # SQL bucket min/max preserves spikes and endpoints without loading all points.
    ranked = select(MetricPoint.step, MetricPoint.value, MetricPoint.timestamp, func.row_number().over(order_by=(MetricPoint.step, MetricPoint.timestamp, MetricPoint.id)).label("rownum")).where(MetricPoint.run_id == run.id, MetricPoint.key == key).subquery()
    count = db.scalar(select(func.count()).select_from(ranked))
    stride = max(1, (count + limit - 1) // limit)
    rows = db.execute(select(ranked).where((ranked.c.rownum % stride == 0) | (ranked.c.rownum == 1) | (ranked.c.rownum == count)).order_by(ranked.c.rownum)).mappings().all()
    return {"key": key, "total_points": count, "downsampling": "uniform stride plus first/last" if stride > 1 else None, "points": [{"step": r["step"], "value": r["value"], "timestamp": r["timestamp"]} for r in rows]}


@router.post("/runs:compare")
def compare(payload: Compare, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    result = []
    for identity in payload.ids:
        run, _ = item_access(db, request, user, Run, identity)
        result.append(run_view(db, run, True))
    if len({r["project_id"] for r in result}) != 1:
        raise HTTPException(422, "Compare runs in the same project")
    return {"runs": result}
