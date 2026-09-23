import base64
import hashlib
import json
import re
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from .deps import membership_for, require_editor
from .models import AuditEvent, Project
from .tracking_models import ApiKey, Idempotency

SECRET_KEY = re.compile(r"authorization|password|secret|token|api.?key|cookie", re.I)
SECRET_VALUE = re.compile(r"(?i)(bearer\s+)[\w.\-]+|fr_live_[\w\-]+|sk-[\w\-]{8,}")


def redact(value, depth=0):
    if depth > 12:
        return "[depth limit]"
    if isinstance(value, dict):
        return {str(k): "[redacted]" if SECRET_KEY.search(str(k)) else redact(v, depth + 1) for k, v in list(value.items())[:100]}
    if isinstance(value, list):
        return [redact(v, depth + 1) for v in value[:100]]
    if isinstance(value, str):
        return SECRET_VALUE.sub("[redacted]", value[:16000])
    return value


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def record(db, user, project, action, resource, detail=None):
    db.add(AuditEvent(actor_id=user.id, workspace_id=project.workspace_id, action=action, resource_type=resource.__tablename__, resource_id=str(resource.id), detail=detail or {}))


def project_access(db: Session, request: Request, user, project_id: UUID, scope="tracking:read"):
    project = db.get(Project, project_id)
    if not project or project.archived_at:
        raise HTTPException(404, "Project not found")
    membership = membership_for(db, project.workspace_id, user.id)
    key: ApiKey | None = getattr(request.state, "api_key", None)
    if key and (key.project_id != project.id or scope not in key.scopes):
        raise HTTPException(403, f"API key requires {scope} permission for this project")
    if scope != "tracking:read":
        require_editor(membership)
    return project


def item_access(db, request, user, model, identity, scope="tracking:read", lock=False):
    query = select(model).where(model.id == identity)
    if lock:
        query = query.with_for_update()
    item = db.scalar(query)
    if not item:
        raise HTTPException(404, "Resource not found")
    project = project_access(db, request, user, item.project_id, scope)
    return item, project


def serialize(row, fields):
    return {key: getattr(row, key) for key in fields.split()}


def cursor_page(db, query, model, cursor=None, limit=50):
    if cursor:
        try:
            identity = UUID(base64.urlsafe_b64decode(cursor.encode()).decode())
        except (ValueError, UnicodeError):
            raise HTTPException(422, "Invalid pagination cursor")
        query = query.where(model.id < identity)
    items = list(db.scalars(query.order_by(model.id.desc()).limit(limit + 1)))
    more = len(items) > limit
    return items[:limit], {"has_more": more, "next_cursor": base64.urlsafe_b64encode(str(items[limit - 1].id).encode()).decode() if more else None}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def replay(db, request, project_id, payload):
    raw = request.headers.get("Idempotency-Key")
    if not raw:
        return None, None
    if len(raw) > 120:
        raise HTTPException(422, "Idempotency key exceeds 120 characters")
    key = f"{request.url.path}:{raw}"
    if len(key) > 200:
        key = hashlib.sha256(key.encode()).hexdigest()
    prior = db.get(Idempotency, (project_id, key))
    if prior:
        if prior.fingerprint != fingerprint(payload):
            raise HTTPException(409, "Idempotency key was reused with a different payload")
        return key, prior.response
    return key, None


def remember(db, project_id, key, payload, response):
    if key:
        from fastapi.encoders import jsonable_encoder
        db.add(Idempotency(project_id=project_id, key=key, fingerprint=fingerprint(payload), response=jsonable_encoder(response)))
