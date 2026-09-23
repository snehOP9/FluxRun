"""Real HTTP/Postgres/S3 tracking smoke, isolated in a named validation workspace."""
import hashlib
import json
import os
import secrets
import time
from datetime import datetime, timezone
from uuid import uuid4
import httpx


def check():
    origin = {"Origin": "http://localhost:5173"}
    client = httpx.Client(base_url="http://localhost:8000", headers=origin, timeout=30)
    def call(method, path, expected=200, **kwargs):
        response = client.request(method, "/api/v1" + path, **kwargs)
        assert response.status_code == expected, (path, response.status_code, response.text[:500])
        return response.json() if response.content else None
    call("POST", "/auth/login", json={"email": os.environ["LOCAL_ADMIN_EMAIL"], "password": os.environ["LOCAL_ADMIN_PASSWORD"]})
    assert client.get("/readyz").status_code == 200
    suffix = uuid4().hex[:10]
    workspace = call("POST", "/workspaces", 201, json={"name": "Validation " + suffix, "slug": "verify-" + suffix})
    project = call("POST", f"/workspaces/{workspace['id']}/projects", 201, json={"name": "Tracking verification", "slug": "tracking"})
    experiment = call("POST", f"/projects/{project['id']}/experiments", 201, json={"name": "SDK contract"})
    token = call("POST", f"/projects/{project['id']}/keys", 201, json={"name": "Verification key", "scopes": ["tracking:read", "tracking:write", "artifacts:write"]})
    client.cookies.clear(); client.headers["Authorization"] = "Bearer " + token["secret"]
    run = call("POST", f"/experiments/{experiment['id']}/runs", 201, json={"name": "batch check"}, headers={"Idempotency-Key": suffix})
    replay = call("POST", f"/experiments/{experiment['id']}/runs", 201, json={"name": "batch check"}, headers={"Idempotency-Key": suffix})
    assert replay["id"] == run["id"]
    path = f"/runs/{run['id']}"
    call("POST", path + "/params:log", 204, json={"params": {"seed": 42}})
    call("POST", path + "/params:log", 204, json={"params": {"seed": 42}})
    call("POST", path + "/params:log", 409, json={"params": {"seed": 43}})
    now = datetime.now(timezone.utc).isoformat()
    points = [{"id": str(uuid4()), "key": "loss", "value": 1 / (step + 1), "step": step, "timestamp": now} for step in range(1001)]
    started = time.perf_counter()
    assert call("POST", path + "/metrics:log-batch", json={"points": points})["accepted"] == 1001
    elapsed = time.perf_counter() - started
    assert call("POST", path + "/metrics:log-batch", json={"points": points})["accepted"] == 0
    data = b'{"source":"real S3 round trip","demo":true}'
    intent = {"path": "reports/result.json", "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "content_type": "application/json"}
    call("POST", path + "/artifacts", 422, json={**intent, "path": "../escape.json"})
    artifact = call("POST", path + "/artifacts", 201, json=intent)
    call("PUT", f"/artifacts/{artifact['id']}/content", content=data)
    downloaded = client.get(f"/api/v1/artifacts/{artifact['id']}/download")
    assert downloaded.content == data
    assert "attachment" in downloaded.headers["content-disposition"]
    call("POST", path + "/finish", json={"status": "succeeded"})
    call("POST", path + "/finish", 409, json={"status": "failed"})
    assert call("GET", path)["metrics"]["loss"] == 0.000999000999000999
    call("POST", "/workspaces", 403, json={"name": "No administration", "slug": "forbidden"})
    client.headers.pop("Authorization")
    call("POST", "/auth/signup", 201, json={"email": f"verify-{suffix}@example.com", "password": secrets.token_urlsafe(20), "display_name": "Isolation tester"})
    call("GET", path, 404)
    print(json.dumps({"passed": ["readiness", "login", "scoped_key", "idempotent_run", "immutable_params", "1001_metrics", "retry_dedup", "path_traversal", "s3_checksum", "terminal_state", "no_key_admin", "workspace_isolation"], "batch_ms": round(elapsed * 1000, 2)}))


if __name__ == "__main__": check()
