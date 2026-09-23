import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .tracking_models import Identity, JSONValue


class Trace(Identity, Base):
    __tablename__ = "traces"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float] = mapped_column(Float, index=True)
    environment: Mapped[str] = mapped_column(String(40))
    session_id: Mapped[str | None] = mapped_column(String(128), index=True)
    request_preview: Mapped[str | None] = mapped_column(Text)
    response_preview: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float | None] = mapped_column(Float)
    span_count: Mapped[int] = mapped_column(Integer)
    tags: Mapped[dict] = mapped_column(JSONValue, default=dict)
    digest: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("registry_versions.id"))


class Span(Base):
    __tablename__ = "spans"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    trace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("traces.id", ondelete="CASCADE"), primary_key=True)
    parent_id: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float] = mapped_column(Float)
    attributes: Mapped[dict] = mapped_column(JSONValue)
    input: Mapped[object | None] = mapped_column(JSONValue)
    output: Mapped[object | None] = mapped_column(JSONValue)
    events: Mapped[list] = mapped_column(JSONValue)
    input_truncated: Mapped[bool] = mapped_column(Boolean)
    output_truncated: Mapped[bool] = mapped_column(Boolean)
    orphan: Mapped[bool] = mapped_column(Boolean)


class EvaluationCase(Identity, Base):
    __tablename__ = "evaluation_cases"
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("registry_versions.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSONValue)


class Evaluation(Identity, Base):
    __tablename__ = "evaluations"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("registry_versions.id"))
    target_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("registry_versions.id"))
    target_type: Mapped[str] = mapped_column(String(40))
    scorers: Mapped[list] = mapped_column(JSONValue)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer)
    aggregates: Mapped[dict] = mapped_column(JSONValue, default=dict)
    error: Mapped[str | None] = mapped_column(String(1000))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class EvaluationResult(Identity, Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (UniqueConstraint("evaluation_id", "case_id", name="uq_evaluation_case_result"),)
    evaluation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluations.id"), index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_cases.id"))
    input: Mapped[object] = mapped_column(JSONValue)
    expected: Mapped[object | None] = mapped_column(JSONValue)
    actual: Mapped[object | None] = mapped_column(JSONValue)
    scores: Mapped[dict] = mapped_column(JSONValue)
    status: Mapped[str] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(String(1000))


class ReviewQueue(Identity, Base):
    __tablename__ = "review_queues"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    questions: Mapped[list] = mapped_column(JSONValue)
    assignees: Mapped[list] = mapped_column(JSONValue)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class ReviewItem(Identity, Base):
    __tablename__ = "review_items"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    queue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("review_queues.id"), index=True)
    trace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("traces.id", ondelete="SET NULL"))
    result_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evaluation_results.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    answers: Mapped[dict] = mapped_column(JSONValue, default=dict)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
