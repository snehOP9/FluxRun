"""Typed tracking client with bounded retries and background metric batches."""
from __future__ import annotations
import atexit
import hashlib
import json
import logging
import math
import mimetypes
import os
import platform
import random
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4
import httpx
from .errors import AuthenticationError, AuthorizationError, ConflictError, FluxRunError, NotFoundError, RateLimitError, TransportError, ValidationError

logger = logging.getLogger("fluxrun.sdk")


class FluxRun:
    def __init__(self, url: str | None = None, api_key: str | None = None, project: str | None = None, timeout: float = 10, spool_dir: str | None = None):
        """Explicit settings override FLUXRUN_URL, FLUXRUN_API_KEY and FLUXRUN_PROJECT."""
        self.url = (url or os.getenv("FLUXRUN_URL", "http://localhost:8000")).rstrip("/")
        self.project = project or os.getenv("FLUXRUN_PROJECT")
        self.api_key = api_key or os.getenv("FLUXRUN_API_KEY")
        self.spool_dir = Path(spool_dir or os.environ["FLUXRUN_SPOOL_DIR"]) if spool_dir or os.getenv("FLUXRUN_SPOOL_DIR") else None
        if not self.url.startswith(("http://", "https://")): raise ValueError("Server URL must use HTTP(S)")
        self.http = httpx.Client(base_url=self.url, timeout=timeout, headers={"Authorization": f"Bearer {self.api_key}", "User-Agent": "fluxrun-sdk/0.4.0"})
        self._runs: list[RunHandle] = []
        atexit.register(self.close)

    def request(self, method: str, path: str, *, json: Any = None, content: bytes | None = None, key: str | None = None) -> Any:
        """Send a request, retry transport/429/5xx up to three attempts."""
        headers = {"Idempotency-Key": key or uuid4().hex} if method == "POST" else {}
        last: Exception | None = None
        for attempt in range(3):
            try:
                response = self.http.request(method, path, json=json, content=content, headers=headers)
                if response.status_code < 400:
                    return response.json() if response.content else None
                detail = response.json().get("error", {})
                message = f"{detail.get('message', response.reason_phrase)} (request {detail.get('request_id', 'unknown')})"
                cls = {401: AuthenticationError, 403: AuthorizationError, 404: NotFoundError, 409: ConflictError, 422: ValidationError, 429: RateLimitError}.get(response.status_code, FluxRunError)
                last = cls(message)
                if response.status_code not in {429, 502, 503, 504}: raise last
            except httpx.TransportError as exc:
                last = TransportError(type(exc).__name__ + ": server unreachable")
            if attempt < 2: time.sleep(0.2 * 2**attempt + random.random() * 0.1)
        raise last or TransportError("Request failed")

    def get_or_create_experiment(self, name: str) -> SimpleNamespace:
        """Resolve an experiment in the configured project; creation is idempotent by name."""
        if not self.project: raise ValueError("Set FLUXRUN_PROJECT or pass project to FluxRun")
        return SimpleNamespace(**self.request("POST", f"/api/v1/projects/{self.project}/experiments", json={"name": name}))

    def start_run(self, experiment: str, name: str, capture_environment: bool = True, parent_run_id: str | None = None) -> RunHandle:
        """Create a tracked run; use as a context manager to flush and finish."""
        source = environment_metadata() if capture_environment else {}
        result = self.request("POST", f"/api/v1/experiments/{experiment}/runs", json={"name": name, "source": source, "parent_run_id": parent_run_id})
        run = RunHandle(self, result["id"])
        self._runs.append(run)
        return run

    def close(self) -> None:
        """Bounded flush of active metric buffers and close the HTTP client."""
        if self.http.is_closed: return
        for run in self._runs:
            try: run.close()
            except FluxRunError: logger.warning("Metric flush failed during client shutdown")
        self.http.close()
        atexit.unregister(self.close)

    def replay_spool(self) -> int:
        """Replay opted-in metric batches idempotently. Artifacts are never spooled."""
        count = 0
        if self.spool_dir and self.spool_dir.exists():
            for path in sorted(self.spool_dir.glob("*.json"))[:100]:
                data = json.loads(path.read_text())
                self.request("POST", data["path"], json=data["payload"], key=data["key"])
                path.unlink(); count += 1
        return count


class RunHandle:
    def __init__(self, client: FluxRun, identity: str):
        self.client, self.id = client, identity
        self._points: list[dict] = []
        self._lock = threading.Lock()
        self._flush_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._background, daemon=True, name="fluxrun-metrics")
        self._thread.start()

    def __enter__(self) -> RunHandle: return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        try:
            self.close()
            self.client.request("POST", f"/api/v1/runs/{self.id}/finish", json={"status": "failed" if exc else "succeeded", "error": type(exc).__name__ if exc else None})
        except FluxRunError:
            if exc is None: raise
            logger.warning("Tracking failed while reporting the original training exception")
        return False

    def log_params(self, values: dict[str, Any]) -> None:
        """Record immutable configuration; changing an existing key raises ConflictError."""
        self.client.request("POST", f"/api/v1/runs/{self.id}/params:log", json={"params": values})

    def log_tags(self, values: dict[str, str]) -> None:
        """Upsert mutable run annotations."""
        self.client.request("POST", f"/api/v1/runs/{self.id}/tags:upsert", json={"tags": values})

    def log_metric(self, key: str, value: float, step: int = 0) -> None:
        """Buffer one finite scalar. The buffer flushes every two seconds or 500 points."""
        if not math.isfinite(value): raise ValueError("Metric values must be finite")
        if self._stop.is_set(): raise ValueError("Run has already closed")
        point = {"id": str(uuid4()), "key": key, "value": value, "step": step, "timestamp": datetime.now(timezone.utc).isoformat()}
        with self._lock:
            self._points.append(point)
            should_flush = len(self._points) >= 500
        if should_flush: self.flush()

    def log_metrics(self, values: dict[str, float], step: int = 0) -> None:
        """Buffer multiple scalar measurements at the same step."""
        for key, value in values.items(): self.log_metric(key, value, step)

    def _background(self) -> None:
        while not self._stop.wait(2):
            try: self.flush()
            except FluxRunError: logger.warning("Metric transport failed; batch retained for retry")

    def flush(self) -> None:
        """Flush queued points transactionally; failed batches retain their original IDs."""
        with self._flush_lock:
            with self._lock:
                points, self._points = self._points, []
            for offset in range(0, len(points), 1000):
                payload = {"points": points[offset:offset + 1000]}
                path, key = f"/api/v1/runs/{self.id}/metrics:log-batch", uuid4().hex
                try: self.client.request("POST", path, json=payload, key=key)
                except FluxRunError:
                    if self.client.spool_dir:
                        directory = self.client.spool_dir
                        directory.mkdir(parents=True, exist_ok=True)
                        files = list(directory.glob("*.json"))
                        if sum(p.stat().st_size for p in files) < 10 * 1024 * 1024 and len(files) < 100:
                            (directory / f"{key}.json").write_text(json.dumps({"path": path, "payload": {"points": points[offset:]}, "key": key}))
                        else:
                            with self._lock: self._points = points[offset:] + self._points
                    else:
                        with self._lock: self._points = points[offset:] + self._points
                    raise

    def log_artifact(self, filename: str, path: str | None = None) -> dict:
        """Upload an explicit file with SHA-256 verification (32 MiB maximum)."""
        source = Path(filename)
        if source.stat().st_size > 33554432: raise ValueError("Artifact exceeds 32 MiB limit")
        data = source.read_bytes()
        artifact = self.client.request("POST", f"/api/v1/runs/{self.id}/artifacts", json={"path": path or source.name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "content_type": mimetypes.guess_type(source.name)[0] or "application/octet-stream"})
        return self.client.request("PUT", f"/api/v1/artifacts/{artifact['id']}/content", content=data)

    def close(self) -> None:
        """Stop background flushing and flush outstanding measurements."""
        self._stop.set()
        self._thread.join(timeout=1)
        self.flush()


def environment_metadata() -> dict:
    """Capture an allowlist of runtime and Git metadata; never enumerate environment variables."""
    result: dict[str, Any] = {"python": platform.python_version(), "os": platform.system(), "cpu_count": os.cpu_count()}
    for name, args in {"git_commit": ["rev-parse", "HEAD"], "git_branch": ["branch", "--show-current"], "git_dirty": ["status", "--porcelain"]}.items():
        try:
            value = subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL, timeout=2).decode().strip()
            result[name] = bool(value) if name == "git_dirty" else value
        except (OSError, subprocess.SubprocessError): pass
    return result
