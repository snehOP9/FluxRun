"""Guard the Docker Compose startup dependency contract."""

import os
from pathlib import Path

os.environ.setdefault('ENVIRONMENT', 'test')

from fastapi.testclient import TestClient
from fluxrun_api.main import app


COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"


def test_compose_api_healthcheck_calls_a_real_successful_endpoint():
    compose = COMPOSE.read_text(encoding="utf-8")
    api_section = compose.split("\n  api:", 1)[1].split("\n  worker:", 1)[0]
    assert "http://127.0.0.1:8000/healthz" in api_section
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_web_waits_for_api_and_worker_waits_for_minio():
    compose = COMPOSE.read_text(encoding="utf-8")
    worker_section = compose.split("\n  worker:", 1)[1].split("\n  web:", 1)[0]
    web_section = compose.split("\n  web:", 1)[1].split("\nvolumes:", 1)[0]
    assert "minio:\n        condition: service_healthy" in worker_section
    assert "api:\n        condition: service_healthy" in web_section
