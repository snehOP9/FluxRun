import hashlib
from pathlib import PurePosixPath
from tempfile import SpooledTemporaryFile
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from botocore.exceptions import BotoCoreError, ClientError

from ..config import get_settings
from ..contracts import ArtifactIntent
from ..db import get_db
from ..deps import current_user, mutation_guard
from ..domain import item_access, serialize
from ..models import User
from ..storage import s3
from ..tracking_models import Artifact, Run

router = APIRouter(prefix="/api/v1", tags=["artifacts"], dependencies=[Depends(mutation_guard)])
FIELDS = "id run_id project_id path content_type size sha256 status created_at"


def safe_path(path):
    if "\\" in path or "\x00" in path or any(ord(c) < 32 for c in path) or path.startswith("/") or ":" in path or any(p in {".", "..", ""} for p in path.split("/")):
        raise HTTPException(422, "Artifact path must be a relative logical path without traversal")
    return path


@router.get("/runs/{identity}/artifacts")
def list_artifacts(identity: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item_access(db, request, user, Run, identity)
    return [serialize(a, FIELDS) for a in db.scalars(select(Artifact).where(Artifact.run_id == identity).order_by(Artifact.path).limit(1000))]


@router.post("/runs/{identity}/artifacts", status_code=201)
def intent(identity: UUID, payload: ArtifactIntent, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    run, _ = item_access(db, request, user, Run, identity, "artifacts:write", lock=True)
    path = safe_path(payload.path)
    if payload.size > get_settings().max_artifact_bytes:
        raise HTTPException(413, "Artifact exceeds configured size limit")
    old = db.scalar(select(Artifact).where(Artifact.run_id == identity, Artifact.path == path))
    if old:
        if old.sha256 != payload.sha256 or old.size != payload.size:
            raise HTTPException(409, "An artifact with different content already uses this path")
        return serialize(old, FIELDS)
    item = Artifact(run_id=identity, project_id=run.project_id, created_by=user.id, object_key=f"{run.project_id}/{run.id}/{uuid4().hex}", **payload.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    return serialize(item, FIELDS)


@router.put("/artifacts/{identity}/content")
async def upload(identity: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    artifact, _ = item_access(db, request, user, Artifact, identity, "artifacts:write", lock=True)
    maximum = min(get_settings().max_artifact_bytes, artifact.size)
    size, digest = 0, hashlib.sha256()
    with SpooledTemporaryFile(max_size=1024 * 1024) as temporary:
        async for chunk in request.stream():
            size += len(chunk)
            if size > maximum:
                raise HTTPException(413, "Upload exceeds declared artifact size")
            digest.update(chunk); temporary.write(chunk)
        if size != artifact.size or digest.hexdigest() != artifact.sha256:
            raise HTTPException(422, "Upload checksum or size differs from intent; retry with original bytes")
        temporary.seek(0)
        try:
            s3().upload_fileobj(temporary, get_settings().s3_bucket, artifact.object_key, ExtraArgs={"ContentType": artifact.content_type, "Metadata": {"sha256": artifact.sha256}})
        except (BotoCoreError, ClientError):
            raise HTTPException(503, "Object storage is unavailable; run metadata is safe. Retry the upload.")
    artifact.status = "complete"; db.commit()
    return serialize(artifact, FIELDS)


@router.get("/artifacts/{identity}/download")
def download(identity: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    artifact, _ = item_access(db, request, user, Artifact, identity)
    if artifact.status != "complete":
        raise HTTPException(409, "Upload has not completed")
    try:
        body = s3().get_object(Bucket=get_settings().s3_bucket, Key=artifact.object_key)["Body"]
    except (BotoCoreError, ClientError):
        raise HTTPException(503, "Artifact storage is unavailable; metadata is still accessible")
    def stream():
        try:
            yield from body.iter_chunks(65536)
        finally:
            body.close()
    return StreamingResponse(stream(), media_type="application/octet-stream", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(PurePosixPath(artifact.path).name)}", "X-Content-Type-Options": "nosniff"})


@router.get("/artifacts/{identity}/preview")
def preview(identity: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    artifact, _ = item_access(db, request, user, Artifact, identity)
    suffix = PurePosixPath(artifact.path).suffix.lower()
    if suffix not in {".txt", ".json", ".csv", ".md", ".log"}:
        raise HTTPException(415, "This file requires download; active content is never rendered inline")
    if artifact.status != "complete":
        raise HTTPException(409, "Upload has not completed")
    try:
        response = s3().get_object(Bucket=get_settings().s3_bucket, Key=artifact.object_key, Range="bytes=0-65535")
        with response["Body"] as body:
            content = body.read().decode("utf-8", errors="replace")
    except (BotoCoreError, ClientError):
        raise HTTPException(503, "Artifact storage is unavailable")
    return {"text": content, "truncated": artifact.size > 65536}
