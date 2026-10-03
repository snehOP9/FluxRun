"""Vercel/FastAPI entrypoint.

The application implementation stays in fluxrun_api.main; exposing `app` from a
root-level main.py lets Vercel's FastAPI framework detection find it when the
project root is configured as apps/api.
"""

from fluxrun_api.main import app

__all__ = ["app"]
