import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import database
from app.extraction import detect_citation_markers, extract_claims_and_links
from app.models import BlockType, CoverageStatus, DocumentBlock, IdentityStatus, Passage, Reference, ResolvedSource
from app.resolution import _matches_reference, _parse_crossref_work
from app.pipeline import create_job, run_pipeline
from main import app, verify_report


class QualityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.enterContext(patch.object(database, "_DB", Path(temp.name) / "test.sqlite"))
        database.init_db()

    async def test_missing_and_misleading_markers_stay_visible(self):
        text = "Scores rose [1]. Scores fell [9]. Attendance increased by seventeen percent."
        block = DocumentBlock(block_id="b", document_id="d", block_type=BlockType.text, text=text)
        ref = Reference(ref_id="r", document_id="d", raw_marker="[1]", raw_entry="Reference")
        claims, links, issues = await extract_claims_and_links([block], [ref])
        self.assertEqual(len(claims), 3)
        self.assertEqual([link.claim_id for link in links], [claims[0].claim_id])
        self.assertEqual(claims[1].unmatched_markers, ["[9]"])
        self.assertIn("Missing citation", claims[2].mapping_issue)
        for marker in ("[1,9]", "[1–999999]"):
            self.assertEqual(detect_citation_markers(block.model_copy(update={"text": marker}), [ref])[0][3], [])

    def test_crossref_collective_author_and_subtitle(self):
        title, authors, year, doi = _parse_crossref_work({
            "title": ["<i>Planck</i> 2018 results"], "subtitle": ["VI. Cosmological parameters"],
            "author": [{"name": "Planck Collaboration"}], "published": {"date-parts": [[2020]]},
            "DOI": "10.1051/0004-6361/201833910",
        })
        ref = Reference(document_id="d", ref_id="r", raw_entry="", doi=doi, year=2020,
                        title="Planck 2018 results. VI. Cosmological parameters", authors=["Planck Collaboration"])
        self.assertTrue(_matches_reference(ref, title, authors, year))

    def test_private_jobs_and_submission_limits(self):
        job = create_job("report.txt", "text/plain", hashlib.sha256(b"private").hexdigest())
        with TestClient(app) as client:
            for suffix in ("", "/claims", "/report"):
                self.assertEqual(client.get(f"/api/verify/{job.job_id}{suffix}").status_code, 404)
            response = client.get(f"/api/verify/{job.job_id}", headers={"Authorization": "Bearer private"})
            self.assertEqual(response.status_code, 200)
            with patch.dict("os.environ", {"VERIFICATION_ACCESS_KEY": "workspace-code"}):
                self.assertEqual(client.post("/api/verify", json={"text": "test"}).status_code, 401)
        for i in range(4):
            self.assertTrue(database.reserve_verification(str(i), "one", 10000))
        self.assertFalse(database.reserve_verification("busy", "two", 10000))
        for i in range(4):
            database.finish_verification(str(i))
        for i in range(4, 8):
            self.assertTrue(database.reserve_verification(str(i), "one", 10001))
            database.finish_verification(str(i))
        self.assertFalse(database.reserve_verification("over", "one", 10001))
        self.assertTrue(database.reserve_verification("later", "one", 13601))

    async def test_benchmark_from_manuscript_through_report(self):
        fixture = (Path(__file__).parent / "fixtures" / "verification-benchmark.md").read_text()
        manuscript = fixture.split("```text\n")[1].split("\n```")[0]
        modern = "The inferred value of the Hubble constant is 67.4 under base cosmology."
        history = "The historical relation yields approximately 500 km/s/Mpc."
        update = {"title": "Later comparison", "year": "2020", "url": "https://example.org/newer", "text": modern}

        async def resolve(refs):
            return [ResolvedSource(source_id=f"s{n}", ref_id=ref.ref_id, canonical_doi=ref.doi,
                    matched_title=ref.title, identity_status=IdentityStatus.matched, coverage=CoverageStatus.full_text,
                    newer_works=[update] if ref.year == 1929 else []) for n, ref in enumerate(refs)]

        async def retrieve(source, claims, client):
            text = history if source.newer_works else modern
            passage = Passage(passage_id=f"p{source.source_id}", source_id=source.source_id,
                              verbatim_text=text, page=1, section="Results")
            return source, [passage]

        async def classify(claim, passages, coverage, title, newer):
            result = {"verdict": "CONTRADICTORY" if "90 km" in claim else "SUPPORTED",
                      "evidence_passage_ids": [passages[0]["passage_id"]], "issue_flags": [],
                      "explanation": "Compared the same model and units."}
            if "regardless of the cosmological model" in claim:
                result["verdict"] = "PARTLY_SUPPORTED"
            if "salinity" in claim:
                result["verdict"] = "UNSUPPORTED"
            if newer and "modern estimate" in claim:
                result.update(update_url=update["url"], update_quote=modern, update_reason="The later estimate revised the value.")
            return result

        with patch("app.pipeline.resolve_all_references", resolve), patch("app.pipeline.retrieve_source", retrieve), patch("app.verification.classify_claim_gemini", classify):
            job = create_job("benchmark.txt", "text/plain")
            await run_pipeline(job.job_id, manuscript.encode(), "benchmark.txt", "text/plain")
        report = await verify_report(job.job_id)
        from benchmark import evaluate
        evaluation = evaluate(report)
        self.assertEqual(evaluation["passed"], evaluation["expected"], evaluation)
        self.assertEqual(evaluate({"rows": []})["passed"], 0)
        self.assertEqual(evaluate({"rows": [*report["rows"], report["rows"][0]]})["passed"], evaluation["expected"] - 1)
        rows = report["rows"]
        self.assertEqual(len(rows), 8)
        self.assertEqual([r["assessment"]["semantic_verdict"] if r["assessment"] else None for r in rows],
                         ["SUPPORTED", "CONTRADICTORY", "POSSIBLY_OUTDATED", None, None, "PARTLY_SUPPORTED", "UNSUPPORTED", "SUPPORTED"])
        self.assertEqual(rows[2]["assessment"]["update_evidence"]["quote"], modern)
        self.assertEqual(rows[0]["coverage"], "full_text")
        self.assertEqual(rows[0]["evidence"][0]["page"], 1)
        self.assertEqual(rows[3]["marker"], "[9]")
        self.assertIsNone(rows[3]["reference"])
        self.assertIn("Missing citation", rows[4]["review_reason"])

    def test_confirmed_doi_accepts_provider_author_variants(self):
        from app.resolution import match_provider_work
        ref = Reference(document_id="d", ref_id="r", raw_entry="", title="A study", authors=["Team"])
        candidate = {"title": "A study", "doi": "10.1234/a", "authorships": [{"author": {"display_name": "Individual"}}]}
        self.assertFalse(match_provider_work(ref, "10.1234/a", [candidate], "openalex"))
        self.assertTrue(match_provider_work(ref, "10.1234/a", [candidate], "openalex", verified_doi=True))
        self.assertFalse(match_provider_work(ref, "10.1234/b", [candidate], "openalex", verified_doi=True))

    def test_real_source_pdf_page_trace(self):
        import pymupdf
        from app.retrieval import _parse_pdf
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.pdf"
            with pymupdf.open() as doc:
                doc.new_page()
                page = doc.new_page()
                page.insert_text((36, 60), "Results")
                page.insert_text((36, 120), "Students improved their scores in both cohorts.")
                doc.save(path)
            [passage] = _parse_pdf(path)
            self.assertEqual(passage, ("Students improved their scores in both cohorts.", "Results", 2, None))

    def test_simultaneous_admission_stays_within_capacity(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        gate = Barrier(16)

        def submit(index):
            gate.wait(timeout=10)
            return database.reserve_verification(str(index), str(index), 10000)

        with ThreadPoolExecutor(max_workers=16) as pool:
            self.assertEqual(sum(pool.map(submit, range(16))), 4)

    async def test_one_unknown_passage_invalidates_entire_verdict(self):
        from app.models import Claim
        from app.verification import assess_claim_reference_pair
        from unittest.mock import AsyncMock
        claim = Claim(claim_id="c", block_id="b", document_id="d", normalized_text="Test claim", original_span="Test claim")
        source = ResolvedSource(source_id="s", ref_id="r", coverage=CoverageStatus.full_text, identity_status=IdentityStatus.matched)
        passage = Passage(source_id="s", passage_id="known", verbatim_text="The original finding.")
        response = dict(verdict="SUPPORTED", explanation="Test", issue_flags=[], evidence_passage_ids=["known", "invented"])
        with patch("app.providers._request_json", AsyncMock(return_value=response)):
            result = await assess_claim_reference_pair(claim, source, [passage], False)
        self.assertIsNone(result.semantic_verdict)
        self.assertEqual(result.assessment_status.value, "unable_to_assess")

    def test_abstract_quotes_are_verbatim(self):
        from app.retrieval import _chunk_abstract
        text = "No change. Was it significant? Only in one cohort"
        self.assertEqual(_chunk_abstract(text), ["No change.", "Was it significant?", "Only in one cohort"])
