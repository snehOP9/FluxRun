from sqlalchemy import select
from .config import get_settings
from .db import SessionLocal
from .models import User, Workspace, WorkspaceMembership, WorkspaceRole
from .security import hash_password


def main() -> None:
    settings = get_settings()
    if not settings.local_admin_email or not settings.local_admin_password or settings.local_admin_password.startswith("replace-"):
        raise RuntimeError("Set LOCAL_ADMIN_EMAIL and a non-placeholder LOCAL_ADMIN_PASSWORD before starting FluxRun.")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == settings.local_admin_email.lower()))
        if not user:
            user = User(email=settings.local_admin_email.lower(), display_name="Local owner", password_hash=hash_password(settings.local_admin_password))
            db.add(user)
            db.flush()
        workspace = db.scalar(select(Workspace).where(Workspace.slug == "personal"))
        if not workspace:
            workspace = Workspace(name="Personal workspace", slug="personal", created_by=user.id)
            db.add(workspace)
            db.flush()
            db.add(WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.owner))
        db.commit()
    from .storage import ensure_bucket
    ensure_bucket()


if __name__ == "__main__":
    main()
