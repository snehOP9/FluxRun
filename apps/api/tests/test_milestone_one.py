import os
os.environ.setdefault("ENVIRONMENT", "test")
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fluxrun_api.db import Base, get_db
from fluxrun_api.main import app
from fluxrun_api.models import User, Workspace, WorkspaceMembership, WorkspaceRole
from fluxrun_api.security import hash_password

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def override_db():
    with TestSession() as db:
        yield db


app.dependency_overrides[get_db] = override_db


def seed(email: str, password: str) -> User:
    with TestSession() as db:
        user = User(email=email, display_name=email.split("@")[0], password_hash=hash_password(password))
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def login(client: TestClient, email: str, password: str):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password}, headers={"Origin": "http://localhost:5173"})


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def test_login_creates_httponly_session_and_workspace_project_flow():
    seed("owner@gmail.com", "correct-horse-battery-staple")
    with TestClient(app) as client:
        response = login(client, "owner@gmail.com", "correct-horse-battery-staple")
        assert response.status_code == 200
        assert "httponly" in response.headers["set-cookie"].lower()
        workspace = client.post("/api/v1/workspaces", json={"name": "Research", "slug": "research"}, headers={"Origin": "http://localhost:5173"})
        assert workspace.status_code == 201
        project = client.post(f"/api/v1/workspaces/{workspace.json()['id']}/projects", json={"name": "Churn", "slug": "churn", "description": "Baseline experiments"}, headers={"Origin": "http://localhost:5173"})
        assert project.status_code == 201
        assert project.json()["slug"] == "churn"
        archive = client.post(f"/api/v1/projects/{project.json()['id']}/archive", headers={"Origin": "http://localhost:5173"})
        assert archive.status_code == 204
        assert client.get(f"/api/v1/workspaces/{workspace.json()['id']}/projects").json() == []


def test_workspace_data_is_hidden_from_non_member():
    owner = seed("owner@gmail.com", "correct-horse-battery-staple")
    seed("other@gmail.com", "another-secure-password")
    with TestSession() as db:
        workspace = Workspace(name="Private", slug="private", created_by=owner.id)
        db.add(workspace); db.flush()
        db.add(WorkspaceMembership(workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.owner)); db.commit(); workspace_id = str(workspace.id)
    with TestClient(app) as client:
        assert login(client, "other@gmail.com", "another-secure-password").status_code == 200
        response = client.get(f"/api/v1/workspaces/{workspace_id}/projects")
        assert response.status_code == 404


def test_mutations_reject_missing_origin():
    seed("owner@gmail.com", "correct-horse-battery-staple")
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/login", json={"email": "owner@gmail.com", "password": "correct-horse-battery-staple"}).status_code == 403
