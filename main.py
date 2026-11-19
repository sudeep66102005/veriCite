"""ASGI entry point for deployments launched from the repository root."""
import sys
from pathlib import Path

# Backend modules also run standalone with backend/ on the import path.
sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from backend.main import app

__all__ = ["app"]
