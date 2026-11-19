"""Expose the verification API through the package entry point."""
try:
    from main import app as app
except ImportError:
    from backend.main import app as app
