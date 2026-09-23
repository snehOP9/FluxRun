"""Durable database jobs; Celery/Redis is dispatch, not the source of truth."""
from datetime import UTC, datetime, timedelta
from uuid import UUID
from celery import Celery
from sqlalchemy import delete, func, select
from redis import Redis
from fluxrun_api.config import get_settings
from fluxrun_api.db import SessionLocal
from fluxrun_api.domain import utc
from fluxrun_api.evaluation import score
from fluxrun_api.models import AuditEvent, Project
from fluxrun_api.observability_models import Evaluation, EvaluationCase, EvaluationResult, Trace
from fluxrun_api.registry_models import RegistryVersion
from fluxrun_api.prompts import render_prompt
from fluxrun_api.tracking_models import Artifact, Idempotency
from fluxrun_api.storage import s3

settings = get_settings()
celery = Celery("fluxrun", broker=settings.redis_url)
celery.conf.update(task_serializer="json", accept_content=["json"], timezone="UTC", task_acks_late=True, worker_prefetch_multiplier=1, broker_connection_retry_on_startup=True, task_soft_time_limit=240, task_time_limit=300, beat_schedule={"recover-jobs": {"task": "fluxrun.dispatch", "schedule": 30}, "retention": {"task": "fluxrun.maintenance", "schedule": 3600}})


@celery.task(name="fluxrun.evaluate", autoretry_for=(ConnectionError,), retry_backoff=True, max_retries=3)
def execute_evaluation(identity: str):
    identity = UUID(identity)
    with SessionLocal() as db:
        job = db.scalar(select(Evaluation).where(Evaluation.id == identity).with_for_update())
        if not job or job.status not in {"queued", "running"}: return
        if job.status == "running" and job.lease_until and utc(job.lease_until) > datetime.now(UTC): return
        job.status, job.started_at, job.lease_until = "running", job.started_at or datetime.now(UTC), datetime.now(UTC) + timedelta(minutes=5)
        db.commit()
        cases = list(db.scalars(select(EvaluationCase).where(EvaluationCase.version_id == job.dataset_version_id).order_by(EvaluationCase.position)))
        target = db.get(RegistryVersion, job.target_version_id) if job.target_version_id else None
        for case in cases:
            db.refresh(job)
            if job.cancel_requested: break
            if db.scalar(select(EvaluationResult.id).where(EvaluationResult.evaluation_id == job.id, EvaluationResult.case_id == case.id)): continue
            actual, scores, error = None, {}, None
            try:
                if job.target_type == "prompt_render":
                    actual = render_prompt(target.data, case.data["input"])
                else:
                    if "actual" not in case.data: raise ValueError("Recorded-output case is missing actual")
                    actual = case.data["actual"]
                scores = {s["name"]: score(s["name"], s["config"], case.data, actual) for s in job.scorers}
            except Exception as exc:
                error = "Case could not be evaluated: " + type(exc).__name__
            result = EvaluationResult(evaluation_id=job.id, case_id=case.id, input=case.data["input"], expected=case.data.get("expected"), actual=actual, scores=scores, status="error" if error else "passed" if all(v == 1 for v in scores.values()) else "failed", error=error)
            db.add(result); job.completed += 1; job.lease_until = datetime.now(UTC) + timedelta(minutes=5); db.commit()
        rows = list(db.scalars(select(EvaluationResult).where(EvaluationResult.evaluation_id == job.id)))
        aggregates = {}
        for scorer in job.scorers:
            values = [r.scores[scorer["name"]] for r in rows if scorer["name"] in r.scores]
            aggregates[scorer["name"]] = {"mean": sum(values)/len(values) if values else None, "count": len(values), "errors": sum(r.status == "error" for r in rows)}
        job.aggregates = aggregates
        errors = sum(r.status == "error" for r in rows)
        job.status = "cancelled" if job.cancel_requested else "failed" if errors == len(rows) else "partially_failed" if errors else "succeeded"
        job.ended_at = datetime.now(UTC); job.lease_until = None
        project = db.get(Project, job.project_id)
        db.add(AuditEvent(actor_id=job.created_by, workspace_id=project.workspace_id, action="evaluation.completed", resource_type="evaluation", resource_id=str(job.id), detail={"status": job.status}))
        db.commit()


@celery.task(name="fluxrun.dispatch")
def dispatch():
    Redis.from_url(settings.redis_url).set("fluxrun:worker:heartbeat", datetime.now(UTC).isoformat(), ex=90)
    with SessionLocal() as db:
        ids = list(db.scalars(select(Evaluation.id).where((Evaluation.status == "queued") | ((Evaluation.status == "running") & (Evaluation.lease_until < datetime.now(UTC)))).limit(100)))
    for identity in ids: execute_evaluation.delay(str(identity))


@celery.task(name="fluxrun.maintenance")
def maintenance():
    now = datetime.now(UTC)
    with SessionLocal() as db:
        for project in db.scalars(select(Project)):
            cutoff = now - timedelta(days=int(project.settings.get("trace_retention_days", 30)))
            expired = list(db.scalars(select(Trace.id).where(Trace.project_id == project.id, Trace.created_at < cutoff).limit(1000)))
            if expired:
                db.execute(delete(Trace).where(Trace.id.in_(expired)))
                db.add(AuditEvent(workspace_id=project.workspace_id, action="retention.traces_deleted", resource_type="project", resource_id=str(project.id), detail={"count": len(expired)}))
        for artifact in db.scalars(select(Artifact).where(Artifact.status == "pending", Artifact.created_at < now - timedelta(days=1)).limit(100)):
            s3().delete_object(Bucket=settings.s3_bucket, Key=artifact.object_key)
            artifact.status = "failed"
        db.execute(delete(Idempotency).where(Idempotency.created_at < now - timedelta(days=7)))
        db.commit()
