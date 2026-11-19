"""CiteVerify backend entry point."""
from fastapi import FastAPI

app = FastAPI(title="CiteVerify Backend")


@app.get("/health")
def health() -> dict[str, str]:
    """Report process liveness without making billable provider calls."""
    return {"status": "ok"}
