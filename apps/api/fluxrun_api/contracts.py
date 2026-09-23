"""Write contracts reject typos and bound resource consumption."""
from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Named(Input):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=4000)


class KeyCreate(Input):
    name: str = Field(min_length=2, max_length=120)
    scopes: list[Literal["tracking:read", "tracking:write", "artifacts:write", "registry:write", "traces:write"]] = Field(min_length=1, max_length=5)
    expires_days: int = Field(default=90, ge=1, le=365)


class RunCreate(Input):
    name: str = Field(min_length=1, max_length=120)
    parent_run_id: UUID | None = None
    source: dict[str, Any] = Field(default_factory=dict, max_length=30)
    tags: dict[str, str] = Field(default_factory=dict, max_length=50)


class RunFinish(Input):
    status: Literal["succeeded", "failed", "cancelled"] = "succeeded"
    error: str | None = Field(default=None, max_length=1000)


class Params(Input):
    params: dict[str, Any] = Field(max_length=100)


class Tags(Input):
    tags: dict[str, str] = Field(max_length=100)


class Point(Input):
    id: UUID
    key: str = Field(min_length=1, max_length=128)
    value: float
    step: int = Field(default=0, ge=0, le=2**63 - 1)
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timezone is required")
        return value


class MetricBatch(Input):
    points: list[Point] = Field(min_length=1, max_length=2000)


class Compare(Input):
    ids: list[UUID] = Field(min_length=2, max_length=5)


class ArtifactIntent(Input):
    path: str = Field(min_length=1, max_length=512)
    content_type: str = Field(default="application/octet-stream", max_length=120)
    size: int = Field(ge=0, le=33554432)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Entity(BaseModel):
    """Stable safe envelope; fields are explicitly selected by serializers."""
    model_config = ConfigDict(extra="allow")
    id: UUID


class Page(BaseModel):
    items: list[dict]
    page: dict
