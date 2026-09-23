"""Live integration for immutable registries, tracing, Celery evaluation and reviews."""
import asyncio
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import httpx
from fluxrun import FluxRun
from fluxrun.tracing import configure, start_span, trace


def check():
    client = httpx.Client(base_url="http://localhost:8000/api/v1", headers={"Origin": "http://localhost:5173"}, timeout=30)
    def call(method, path, data=None, expected=200):
        response = client.request(method, path, json=data)
        assert response.status_code == expected, (path, response.status_code, response.text[:500])
        return response.json() if response.content else None
    call("POST", "/auth/login", {"email": os.environ["LOCAL_ADMIN_EMAIL"], "password": os.environ["LOCAL_ADMIN_PASSWORD"]})
    workspace = call("POST", "/workspaces", {"name": "Advanced verification", "slug": "advanced-" + uuid4().hex[:10]}, 201)
    project = call("POST", f"/workspaces/{workspace['id']}/projects", {"name": "Registry and observability", "slug": "evidence"}, 201)
    root = f"/projects/{project['id']}"
    prompt = call("POST", root + "/registry", {"kind": "prompt", "name": "Greeting"}, 201)
    p1 = call("POST", f"/registry/{prompt['id']}/versions", {"data": {"template": "Hello {{name}}"}}, 201)
    p2 = call("POST", f"/registry/{prompt['id']}/versions", {"data": {"template": "Goodbye {{name}}"}}, 201)
    assert p1["number"] == 1 and p2["number"] == 2 and p1["digest"] != p2["digest"]
    call("POST", f"/registry/{prompt['id']}/versions", {"data": {"template": "{{name.__class__}}"}}, 422)
    assert call("POST", f"/versions/{p1['id']}/render", {"variables": {"name": "Ada"}})["rendered"] == "Hello Ada"
    call("PUT", f"/registry/{prompt['id']}/aliases/candidate", {"version_id": p1["id"]})
    call("PUT", f"/registry/{prompt['id']}/aliases/candidate", {"version_id": p2["id"]}, 409)
    call("PUT", f"/registry/{prompt['id']}/aliases/candidate", {"version_id": p2["id"], "expected_version_id": p1["id"]})
    dataset = call("POST", root + "/registry", {"kind": "evaluation_dataset", "name": "Greeting cases"}, 201)
    dv = call("POST", f"/registry/{dataset['id']}/versions", {"data": {"cases": [{"input": {"name": "Ada"}, "expected": "Hello Ada"}, {"input": {"name": "Lin"}, "expected": "Hello Lin"}]}}, 201)
    jobs = [call("POST", root + "/evaluations", {"name": "Compare greeting", "dataset_version_id": dv["id"], "target_type": "prompt_render", "target_version_id": p["id"], "scorers": [{"name": "exact_match"}]}, 202) for p in [p1, p2]]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        jobs = [call("GET", f"/evaluations/{j['id']}") for j in jobs]
        if all(j["status"] not in {"queued", "running"} for j in jobs): break
        time.sleep(0.25)
    assert all(j["status"] == "succeeded" for j in jobs), [(j["status"],j.get("error")) for j in jobs]
    assert [j["aggregates"]["exact_match"]["mean"] for j in jobs] == [1, 0]
    comparison = call("POST", "/evaluations:compare", {"ids": [j["id"] for j in jobs]})
    assert comparison["same_dataset"] is True
    queue = call("POST", root + "/reviews", {"name": "Regression review", "questions": [{"id": "correct", "label": "Is this correct?", "type": "pass_fail"}], "result_ids": [jobs[1]["results"][0]["id"]]}, 201)
    item = call("GET", f"/reviews/{queue['id']}")["items"][0]
    call("POST", f"/review-items/{item['id']}/submit", {"revision": 1, "answers": {"correct": False}})
    call("POST", f"/review-items/{item['id']}/submit", {"revision": 1, "answers": {"correct": True}}, 409)
    now = datetime.now(timezone.utc)
    span = {"id": "a"*16, "name": "LLM", "kind": "llm", "started_at": now.isoformat(), "ended_at": (now+timedelta(milliseconds=120)).isoformat(), "attributes": {"Authorization": "Bearer sensitive", "input_tokens": 20}, "input": {"password": "do-not-store", "question": "Hello"}, "output": "Hello Ada"}
    envelope = {"id": str(uuid4()), "name": "Native trace", "spans": [span]}
    t = call("POST", root + "/traces", envelope, 201)
    stored = call("GET", f"/traces/{t['id']}")
    assert "do-not-store" not in json.dumps(stored) and "Bearer sensitive" not in json.dumps(stored)
    assert stored["spans"][0]["input"]["password"] == "[redacted]"
    bad = {**envelope, "id": str(uuid4()), "spans": [{**span, "parent_id": span["id"]}]}
    call("POST", root + "/traces", bad, 422)
    key = call("POST", root + "/keys", {"name": "SDK verification", "scopes": ["tracking:read", "tracking:write", "traces:write", "artifacts:write", "registry:write"]}, 201)
    sdk = FluxRun(api_key=key["secret"], project=project["id"])
    configure(sdk)
    @trace("retrieve", "retrieval")
    async def retrieve(): await asyncio.sleep(0.001)
    async def flow():
        with start_span("async-parent") as parent:
            await asyncio.gather(retrieve(), retrieve())
            return parent.trace_id
    identity = asyncio.run(flow())
    nested = call("GET", f"/traces/{identity}")
    assert len(nested["spans"]) == 3
    children = [s for s in nested["spans"] if s["parent_id"]]
    assert len({s["parent_id"] for s in children}) == 1
    experiment = sdk.get_or_create_experiment("sdk-batching")
    with sdk.start_run(experiment.id, "1001 SDK measurements") as run:
        for i in range(1001): run.log_metric("loss", 1/(i+1), i)
    assert call("GET", f"/runs/{run.id}")["status"] == "succeeded"
    sdk.close()
    print(json.dumps({"passed": ["immutable_prompt_versions", "strict_rendering", "alias_compare_and_swap", "immutable_cases", "celery_worker", "regression_1_to_0", "per_case_results", "review_conflict", "trace_redaction", "cycle_rejection", "async_context", "sdk_1001_points"]}))


if __name__ == "__main__": check()
