"""veriCite academic research discovery and verification API."""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import httpx
from integrations.providers import SEARCH_PROVIDERS, search_all, unpaywall
from app.pipeline import create_job, run_pipeline
from app.database import init_db, get_job, get_claims
from app.models import JobState

load_dotenv()
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="veriCite Evidence API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://localhost:5173"],
                   allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["*"])

@app.get("/api/health")
def health():
    return {"status": "ok", "providers": list(SEARCH_PROVIDERS)}

@app.get("/api/evidence/search")
async def evidence_search(q: str = Query(min_length=3, max_length=500),
                          limit: int = Query(5, ge=1, le=20),
                          providers: str | None = None):
    selected = [s.strip() for s in providers.split(",") if s.strip()] if providers else None
    try:
        return await search_all(q, limit, selected)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.get("/api/evidence/open-access")
async def open_access(doi: str = Query(min_length=3, max_length=250)):
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            return await unpaywall(client, doi.removeprefix("https://doi.org/"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Unpaywall returned HTTP {exc.response.status_code}") from exc

    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Unpaywall is temporarily unreachable; please retry.") from exc


@app.get("/health")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


class VerifyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)
    filename: str = "document.txt"


@app.post("/api/verify", status_code=202)
async def verify(request: VerifyRequest):
    filename = request.filename if request.filename.lower().endswith((".txt", ".md")) else "document.txt"
    content = request.text.encode("utf-8")
    job = create_job(filename, "text/plain")
    asyncio.create_task(run_pipeline(job.job_id, content, filename, "text/plain"))
    return {"job_id": job.job_id, "status": "queued"}


@app.get("/api/verify/{job_id}")
async def verify_status(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    result = {
        "job_id": job.job_id,
        "job_state": job.job_state.value,
        "current_stage": job.current_stage,
        "error_message": job.error_message,
    }
    if job.job_state == JobState.completed:
        result["report"] = job.report
    return result


@app.get("/api/verify/{job_id}/claims")
async def verify_claims(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.report or not job.report.get("document_id"):
        return {"claims": []}
    return {"claims": [claim.model_dump(mode="json") for claim in get_claims(job.report["document_id"])]}


@app.get("/api/verify/{job_id}/report")
async def verify_report(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.job_state != JobState.completed:
        raise HTTPException(status_code=409, detail="Job has not completed yet")
    return job.report
