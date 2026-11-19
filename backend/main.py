"""veriCite academic research discovery and verification API."""
import asyncio
import os
import hashlib
import secrets
from app.database import save_job
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Path, Query, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import httpx
from integrations.providers import SEARCH_PROVIDERS, TIMEOUT, core_work, search_all, unpaywall
from app.config import GEMINI_API_KEY
from app.pipeline import create_job, run_pipeline
from app.database import init_db, get_job, get_claims, document_links, get_references, get_resolved_source, get_passages
from app.models import JobState
from app.database import reserve_verification, finish_verification

load_dotenv()
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="veriCite Evidence API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://localhost:5173", "https://veri-cite-two.vercel.app"],
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

@app.get("/api/evidence/core/works/{work_id}")
async def core_work_details(work_id: int = Path(gt=0)):
    if not os.getenv("CORE_API_KEY", "").strip():
        raise HTTPException(status_code=503, detail="CORE_API_KEY must be configured")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            return await core_work(client, work_id)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            raise HTTPException(status_code=404, detail="CORE work not found") from exc
        if status == 429:
            retry_after = exc.response.headers.get("Retry-After")
            headers = {"Retry-After": retry_after} if retry_after else None
            raise HTTPException(status_code=429, detail="CORE rate limit reached", headers=headers) from exc
        raise HTTPException(status_code=502, detail=f"CORE returned HTTP {status}") from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="CORE request timed out") from exc
    except (httpx.RequestError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="CORE work details are unavailable") from exc


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
    filename: str = Field("document.txt", max_length=255)


@app.post("/api/verify", status_code=202)
async def verify(request: VerifyRequest, connection: Request, x_verification_key: str = Header("")):
    configured = os.getenv("VERIFICATION_ACCESS_KEY", "")
    if configured and not secrets.compare_digest(configured.encode(), x_verification_key.encode()):
        raise HTTPException(401, "This workspace requires a verification access code.")
    if not GEMINI_API_KEY.strip():
        raise HTTPException(status_code=503, detail="Verification is unavailable until GEMINI_API_KEY is configured on Render.")
    filename = request.filename if request.filename.lower().endswith((".txt", ".md")) else "document.txt"
    content = request.text.encode("utf-8")
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    peer = connection.client.host if connection.client else "unknown"
    if not reserve_verification(digest, peer, int(time.time())):
        raise HTTPException(429, "Verification capacity reached. Try again later.", headers={"Retry-After": "60"})
    try:
        job = create_job(filename, "text/plain", digest)
    except Exception:
        finish_verification(digest)
        raise

    async def run():
        try:
            async with asyncio.timeout(540):
                await run_pipeline(job.job_id, content, filename, "text/plain")
        except TimeoutError:
            current = get_job(job.job_id)
            current.job_state = JobState.failed
            current.error_message = "Verification reached its time limit."
            save_job(current)
        finally:
            finish_verification(digest)
    asyncio.create_task(run())
    return {"job_id": job.job_id, "status": "queued", "access_token": token}


def check_job(job_id, authorization):
    job = get_job(job_id)
    token = authorization.removeprefix("Bearer ") if isinstance(authorization, str) else ""
    if job is None or (job.access_digest and not secrets.compare_digest(
            job.access_digest, hashlib.sha256(token.encode()).hexdigest())):
        raise HTTPException(404, "Job not found")
    return job


@app.get("/api/verify/{job_id}")
async def verify_status(job_id: str, authorization: str | None = Header(None)):
    job = check_job(job_id, authorization)
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
async def verify_claims(job_id: str, authorization: str | None = Header(None)):
    job = check_job(job_id, authorization)
    if not job.report or not job.report.get("document_id"):
        return {"claims": []}
    document_id = job.report["document_id"]
    claims = get_claims(document_id)
    references = {ref.ref_id: ref for ref in get_references(document_id)}
    assessments = {(item["claim_id"], item["ref_id"]): item for item in job.report["assessments"]}
    sources = {ref_id: get_resolved_source(ref_id) for ref_id in references}
    passages = {
        passage.passage_id: passage
        for source in sources.values() if source
        for passage in get_passages(source.source_id)
    }
    links_by_claim = document_links(document_id)
    rows = []
    for claim in claims:
        links = links_by_claim.get(claim.claim_id, [])
        pairs = [(link, None) for link in links] + [(None, marker) for marker in claim.unmatched_markers]
        for link, unresolved in pairs or [(None, None)]:
            ref = references.get(link.ref_id) if link else None
            source = sources.get(ref.ref_id) if ref else None
            assessment = assessments.get((claim.claim_id, ref.ref_id)) if ref else None
            evidence = [
                passages[pid].model_dump(mode="json")
                for pid in (assessment or {}).get("evidence_passage_ids", [])
                if pid in passages and source and passages[pid].source_id == source.source_id
            ]
            rows.append({
                "id": link.link_id if link else f"{claim.claim_id}:{unresolved or 'uncited'}",
                "text": claim.original_span,
                "review_reason": f"Reference {unresolved} is missing." if unresolved else claim.mapping_issue,
                "coverage": source.coverage.value if source else "unavailable",
                "extraction_error": claim.extraction_error,
                "marker": link.citation_marker if link else unresolved,
                "reference": ref.raw_entry if ref else None,
                "doi": (source.canonical_doi if source else None) or (ref.doi if ref else None),
                "source_url": (source.publication_url or source.source_url) if source else None,
                "mapping": link.mapping_status if link else "unmatched",
                "assessment": assessment,
                "evidence": evidence,
            })
    return {"claims": [claim.model_dump(mode="json") for claim in claims], "rows": rows}


@app.get("/api/verify/{job_id}/report")
async def verify_report(job_id: str, authorization: str | None = Header(None)):
    job = check_job(job_id, authorization)
    if job.job_state != JobState.completed:
        raise HTTPException(status_code=409, detail="Job has not completed yet")
    return {**job.report, "rows": (await verify_claims(job_id, authorization)).get("rows", [])}
