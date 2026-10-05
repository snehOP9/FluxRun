import importlib.util
from pathlib import Path

from fluxrun_api.main import app as core_app


def test_vercel_entrypoint_exports_core_fastapi_app():
    entrypoint = Path(__file__).parents[1] / "main.py"
    spec = importlib.util.spec_from_file_location("fluxrun_vercel_entrypoint", entrypoint)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.app is core_app
    assert module.__all__ == ["app"]
