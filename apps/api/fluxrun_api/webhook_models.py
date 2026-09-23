import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .tracking_models import Identity, JSONValue


class Webhook(Identity, Base):
    __tablename__ = "webhooks"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(2000))
    encrypted_secret: Mapped[str] = mapped_column(String(512))
    events: Mapped[list] = mapped_column(JSONValue)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class WebhookDelivery(Identity, Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (UniqueConstraint("webhook_id", "event_id", name="uq_webhook_event"),)
    webhook_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("webhooks.id"))
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audit_events.id"))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    response_code: Mapped[int | None] = mapped_column(Integer)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
