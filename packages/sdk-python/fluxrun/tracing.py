"""Native tracing with contextvars so nesting survives concurrent async tasks."""
from __future__ import annotations
import functools
import inspect
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4
from .client import FluxRun
from .errors import FluxRunError

_client: ContextVar[FluxRun | None] = ContextVar("fluxrun_client", default=None)
_span: ContextVar[SpanHandle | None] = ContextVar("fluxrun_span", default=None)
logger = logging.getLogger("fluxrun.tracing")


def configure(client: FluxRun) -> None:
    """Bind the client for this execution context and its child async tasks."""
    _client.set(client)


class SpanHandle:
    def __init__(self, name: str, kind: str = "function", client: FluxRun | None = None):
        self.client = client or _client.get()
        if not self.client: raise ValueError("Call fluxrun.tracing.configure(client) first")
        self.parent = _span.get()
        self.trace_id = self.parent.trace_id if self.parent else str(uuid4())
        self.spans = self.parent.spans if self.parent else []
        self.data: dict[str, Any] = {"id": uuid4().hex[:16], "parent_id": self.parent.data["id"] if self.parent else None, "name": name, "kind": kind, "status": "ok", "attributes": {}, "events": []}

    @property
    def traceparent(self) -> str:
        """W3C propagation header for this span."""
        return f"00-{self.trace_id.replace('-', '')}-{self.data['id']}-01"

    def __enter__(self) -> SpanHandle:
        self.data["started_at"] = datetime.now(timezone.utc).isoformat()
        self.token = _span.set(self)
        return self

    def set_attribute(self, name: str, value: Any) -> None:
        """Add bounded metadata. Server-side redaction is applied before persistence."""
        self.data["attributes"][name] = value

    def set_input(self, value: Any) -> None:
        """Record explicit input; never implicitly capture all function arguments."""
        self.data["input"] = value

    def set_output(self, value: Any) -> None:
        """Record explicit output, subject to project privacy settings."""
        self.data["output"] = value

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.data["ended_at"] = datetime.now(timezone.utc).isoformat()
        if exc:
            self.data["status"] = "error"
            self.data["events"].append({"name": "exception", "type": type(exc).__name__})
        self.spans.append(self.data)
        _span.reset(self.token)
        if not self.parent:
            try:
                self.client.request("POST", f"/api/v1/projects/{self.client.project}/traces", json={"id": self.trace_id, "name": self.data["name"], "spans": self.spans})
            except FluxRunError:
                if not exc: raise
                logger.warning("Failed to export trace; original application error preserved")
        return False


def start_span(name: str, kind: str = "function", client: FluxRun | None = None) -> SpanHandle:
    """Create a nested span; the root exports one completed trace envelope."""
    return SpanHandle(name, kind, client)


def trace(name: str | None = None, kind: str = "function") -> Callable:
    """Instrument sync or async functions without capturing arguments implicitly."""
    def decorate(function):
        if inspect.iscoroutinefunction(function):
            @functools.wraps(function)
            async def async_wrapper(*args, **kwargs):
                with start_span(name or function.__name__, kind):
                    return await function(*args, **kwargs)
            return async_wrapper
        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            with start_span(name or function.__name__, kind):
                return function(*args, **kwargs)
        return wrapper
    return decorate
