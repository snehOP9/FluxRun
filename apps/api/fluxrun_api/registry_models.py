"""Shared immutable revision model for models, datasets and prompts."""
import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .tracking_models import Identity, JSONValue


class RegistryItem(Identity, Base):
    __tablename__ = "registry_items"
    __table_args__ = (UniqueConstraint("project_id", "kind", "name", name="uq_registry_name"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RegistryVersion(Identity, Base):
    __tablename__ = "registry_versions"
    __table_args__ = (UniqueConstraint("item_id", "number", name="uq_registry_version"),)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("registry_items.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    number: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSONValue)
    digest: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(String(1000), default="")
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"))
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class RegistryAlias(Base):
    __tablename__ = "registry_aliases"
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("registry_items.id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("registry_versions.id"))
    changed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class RunDataset(Base):
    __tablename__ = "run_datasets"
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("registry_versions.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), primary_key=True)
