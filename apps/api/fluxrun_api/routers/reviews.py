from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..contracts import Input
from ..db import get_db
from ..deps import current_user, membership_for, mutation_guard
from ..domain import item_access, project_access, record, serialize
from ..models import User, WorkspaceMembership
from ..observability_models import Evaluation, EvaluationResult, ReviewItem, ReviewQueue, Trace

router = APIRouter(prefix="/api/v1", tags=["reviews"], dependencies=[Depends(mutation_guard)])


class QueueCreate(Input):
    name: str = Field(min_length=2, max_length=120)
    questions: list[dict] = Field(min_length=1, max_length=20)
    assignees: list[UUID] = Field(default_factory=list, max_length=100)
    trace_ids: list[UUID] = Field(default_factory=list, max_length=500)
    result_ids: list[UUID] = Field(default_factory=list, max_length=500)


class Answer(Input):
    revision: int = Field(ge=1)
    answers: dict[str, Any] = Field(max_length=20)
    decline: bool = False


def reviewer(db, user, project, queue):
    member = membership_for(db, project.workspace_id, user.id)
    if member.role.value == "viewer": raise HTTPException(403, "Reviewer permission is required")
    if queue.assignees and str(user.id) not in queue.assignees and member.role.value not in {"owner", "admin"}: raise HTTPException(403, "This queue is assigned to other reviewers")


@router.post("/projects/{project_id}/reviews", status_code=201)
def create(project_id: UUID, payload: QueueCreate, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = project_access(db, request, user, project_id, "registry:write")
    if not payload.trace_ids and not payload.result_ids: raise HTTPException(422, "Select traces or evaluation results to review")
    names = set()
    for question in payload.questions:
        if question.get("type") not in {"pass_fail", "category", "multi_category", "numeric", "text", "expected_answer"} or not question.get("id") or not question.get("label"): raise HTTPException(422, "Each question requires an ID, label and supported type")
        if question["id"] in names: raise HTTPException(422, "Duplicate question ID")
        names.add(question["id"])
        if question["type"] in {"category", "multi_category"} and not question.get("options"): raise HTTPException(422, "Category question requires options")
    for identity in payload.assignees:
        if not db.scalar(select(WorkspaceMembership.id).where(WorkspaceMembership.user_id == identity, WorkspaceMembership.workspace_id == project.workspace_id)): raise HTTPException(422, "Assignee must be a workspace member")
    queue = ReviewQueue(project_id=project_id, name=payload.name, questions=payload.questions, assignees=[str(i) for i in payload.assignees], created_by=user.id)
    db.add(queue); db.flush()
    for identity in set(payload.trace_ids):
        trace, _ = item_access(db, request, user, Trace, identity)
        if trace.project_id != project_id: raise HTTPException(422, "Select traces from this project")
        db.add(ReviewItem(project_id=project_id, queue_id=queue.id, trace_id=identity))
    for identity in set(payload.result_ids):
        result = db.get(EvaluationResult, identity)
        if not result: raise HTTPException(404, "Evaluation result not found")
        job, _ = item_access(db, request, user, Evaluation, result.evaluation_id)
        if job.project_id != project_id: raise HTTPException(422, "Select results from this project")
        db.add(ReviewItem(project_id=project_id, queue_id=queue.id, result_id=identity))
    record(db, user, project, "review_queue.created", queue); db.commit()
    return serialize(queue, "id name project_id questions assignees created_at")


@router.get("/projects/{project_id}/reviews")
def queues(project_id: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project_access(db, request, user, project_id)
    return [serialize(q, "id name questions assignees created_at") for q in db.scalars(select(ReviewQueue).where(ReviewQueue.project_id == project_id).order_by(ReviewQueue.id.desc()).limit(100))]


@router.get("/reviews/{identity}")
def detail(identity: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    queue, project = item_access(db, request, user, ReviewQueue, identity)
    reviewer(db, user, project, queue)
    result = []
    for item in db.scalars(select(ReviewItem).where(ReviewItem.queue_id == identity).order_by(ReviewItem.id).limit(1000)):
        source = db.get(Trace, item.trace_id) if item.trace_id else db.get(EvaluationResult, item.result_id)
        content = {"input": source.request_preview, "output": source.response_preview} if isinstance(source, Trace) else {"input": source.input, "output": source.actual, "expected": source.expected} if source else {"unavailable": "Source removed by retention policy"}
        result.append({**serialize(item, "id status revision answers reviewer_id trace_id result_id"), "content": content})
    return {**serialize(queue, "id name questions assignees created_at"), "items": result}


@router.post("/review-items/{identity}/submit")
def submit(identity: UUID, payload: Answer, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item, project = item_access(db, request, user, ReviewItem, identity, lock=True)
    queue = db.get(ReviewQueue, item.queue_id)
    reviewer(db, user, project, queue)
    if item.revision != payload.revision or item.status != "pending": raise HTTPException(409, "Another reviewer completed this item. Refresh to continue.")
    if not payload.decline:
        if set(payload.answers) != {q["id"] for q in queue.questions}: raise HTTPException(422, "Answer every question exactly once")
        for question in queue.questions:
            value, kind = payload.answers[question["id"]], question["type"]
            valid = True
            if kind == "pass_fail": valid = isinstance(value, bool)
            elif kind == "category": valid = value in question["options"]
            elif kind == "multi_category": valid = isinstance(value, list) and all(v in question["options"] for v in value)
            elif kind == "numeric": valid = isinstance(value, (float, int)) and not isinstance(value, bool) and question.get("min", 0) <= value <= question.get("max", 5)
            else: valid = isinstance(value, str) and len(value) <= 10000
            if not valid: raise HTTPException(422, f"Invalid answer for {question['id']}")
    item.answers, item.reviewer_id, item.revision = payload.answers, user.id, item.revision + 1
    item.status = "declined" if payload.decline else "completed"
    record(db, user, project, "review.completed", item, {"queue_id": str(queue.id), "status": item.status})
    db.commit()
    return serialize(item, "id status revision reviewer_id")
