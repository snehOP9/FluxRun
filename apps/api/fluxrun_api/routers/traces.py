from datetime import datetime
import json
from typing import Any, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..contracts import Input
from ..db import get_db
from ..deps import current_user, mutation_guard
from ..domain import cursor_page, fingerprint, item_access, project_access, redact, serialize
from ..models import User
from ..observability_models import Span, Trace
from ..registry_models import RegistryItem, RegistryVersion

router = APIRouter(prefix="/api/v1", tags=["traces"], dependencies=[Depends(mutation_guard)])
TRACE_FIELDS = "id project_id name status started_at ended_at duration_ms environment session_id request_preview response_preview input_tokens output_tokens cost span_count tags prompt_version_id created_at"
SPAN_FIELDS = "id trace_id parent_id name kind status started_at ended_at duration_ms attributes input output events input_truncated output_truncated orphan"


class SpanIn(Input):
    id: str = Field(pattern=r"^[a-f0-9]{16,32}$")
    parent_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{16,32}$")
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["function", "llm", "retrieval", "tool", "parser", "http"] = "function"
    status: Literal["ok", "error"] = "ok"
    started_at: datetime
    ended_at: datetime
    attributes: dict[str, Any] = Field(default_factory=dict, max_length=50)
    input: Any = None
    output: Any = None
    events: list[dict] = Field(default_factory=list, max_length=50)

    @field_validator("started_at", "ended_at")
    @classmethod
    def timezone_required(cls, value):
        if not value.tzinfo: raise ValueError("Timezone required")
        return value


class TraceIn(Input):
    id: UUID
    name: str = Field(min_length=1, max_length=120)
    environment: str = Field(default="development", max_length=40)
    session_id: str | None = Field(default=None, max_length=128)
    tags: dict[str, str] = Field(default_factory=dict, max_length=50)
    prompt_version_id: UUID | None = None
    spans: list[SpanIn] = Field(min_length=1, max_length=1000)
    cost: float | None = Field(default=None, ge=0)


def validate_tree(spans):
    parents = {span.id: span.parent_id for span in spans}
    if len(parents) != len(spans): raise HTTPException(422, "Duplicate span ID")
    for span in spans:
        if span.ended_at < span.started_at: raise HTTPException(422, "Span end precedes start")
        visited = set()
        current = span.id
        while current in parents:
            if current in visited: raise HTTPException(422, "Cyclic span parent relationship")
            visited.add(current)
            if len(visited) > 100: raise HTTPException(422, "Trace nesting exceeds 100 spans")
            current = parents[current]


def preview(value, limit):
    if value is None or limit == 0: return None, value is not None
    safe = redact(value)
    encoded = json.dumps(safe, ensure_ascii=False) if not isinstance(safe, str) else safe
    return (encoded[:limit], True) if len(encoded) > limit else (safe, False)


@router.post("/projects/{project_id}/traces", status_code=201)
def ingest(project_id: UUID, payload: TraceIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = project_access(db, request, user, project_id, "traces:write")
    validate_tree(payload.spans)
    digest = fingerprint(payload.model_dump())
    existing = db.get(Trace, payload.id)
    if existing:
        if existing.project_id != project_id: raise HTTPException(409, "Trace identifier is unavailable")
        if existing.digest != digest: raise HTTPException(409, "Trace ID reused with different contents")
        return serialize(existing, TRACE_FIELDS)
    if payload.prompt_version_id:
        version, _ = item_access(db, request, user, RegistryVersion, payload.prompt_version_id)
        if version.project_id != project_id or db.get(RegistryItem, version.item_id).kind != "prompt": raise HTTPException(422, "Prompt version must belong to this project")
    limit = int(project.settings.get("trace_preview_chars", 2000)) if project.settings.get("store_trace_content", True) else 0
    start, end = min(s.started_at for s in payload.spans), max(s.ended_at for s in payload.spans)
    root = next((s for s in payload.spans if s.parent_id is None), payload.spans[0])
    tokens = lambda key: sum(max(0, int(s.attributes.get(key, 0))) for s in payload.spans if isinstance(s.attributes.get(key, 0), (int, float)))
    first, _ = preview(root.input, limit); last, _ = preview(root.output, limit)
    as_text = lambda v: v if isinstance(v, str) or v is None else json.dumps(v)
    trace = Trace(id=payload.id, project_id=project_id, name=payload.name, status="error" if any(s.status == "error" for s in payload.spans) else "ok", started_at=start, ended_at=end, duration_ms=(end-start).total_seconds()*1000, environment=payload.environment, session_id=payload.session_id, request_preview=as_text(first), response_preview=as_text(last), input_tokens=tokens("input_tokens"), output_tokens=tokens("output_tokens"), cost=payload.cost, span_count=len(payload.spans), tags=redact(payload.tags), prompt_version_id=payload.prompt_version_id, digest=digest, created_by=user.id)
    db.add(trace); db.flush()
    ids = {s.id for s in payload.spans}
    for span in payload.spans:
        data = span.model_dump(); data["attributes"] = redact(span.attributes); data["events"] = redact(span.events)
        data["input"], data["input_truncated"] = preview(span.input, limit)
        data["output"], data["output_truncated"] = preview(span.output, limit)
        db.add(Span(trace_id=trace.id, duration_ms=(span.ended_at-span.started_at).total_seconds()*1000, orphan=bool(span.parent_id and span.parent_id not in ids), **data))
    db.commit()
    return serialize(trace, TRACE_FIELDS)


@router.get("/projects/{project_id}/traces")
def traces(project_id: UUID, request: Request, q: str = "", status: str | None = None, environment: str | None = None, session: str | None = None, min_duration: float | None = None, min_tokens: int | None = None, cursor: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project_access(db, request, user, project_id)
    query = select(Trace).where(Trace.project_id == project_id, Trace.name.ilike(f"%{q[:120]}%"))
    if status: query = query.where(Trace.status == status)
    if environment: query = query.where(Trace.environment == environment)
    if session: query = query.where(Trace.session_id == session)
    if min_duration is not None: query = query.where(Trace.duration_ms >= min_duration)
    if min_tokens is not None: query = query.where(Trace.input_tokens + Trace.output_tokens >= min_tokens)
    rows, page = cursor_page(db, query, Trace, cursor)
    return {"items": [serialize(t, TRACE_FIELDS) for t in rows], "page": page}


@router.get("/traces/{identity}")
def detail(identity: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    trace, _ = item_access(db, request, user, Trace, identity)
    return {**serialize(trace, TRACE_FIELDS), "spans": [serialize(s, SPAN_FIELDS) for s in db.scalars(select(Span).where(Span.trace_id == identity).order_by(Span.started_at).limit(1000))]}
