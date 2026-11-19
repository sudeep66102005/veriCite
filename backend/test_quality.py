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
            if newer:
                result.update(update_url=update["url"], update_quote=modern, update_reason="The later estimate revised the value.")
            return result

        with patch("app.pipeline.resolve_all_references", resolve), patch("app.pipeline.retrieve_source", retrieve), patch("app.verification.classify_claim_gemini", classify):
            job = create_job("benchmark.txt", "text/plain")
            await run_pipeline(job.job_id, manuscript.encode(), "benchmark.txt", "text/plain")
        report = await verify_report(job.job_id)
        rows = report["rows"]
        self.assertEqual(len(rows), 5)
        self.assertEqual([r["assessment"]["semantic_verdict"] if r["assessment"] else None for r in rows],
                         ["SUPPORTED", "CONTRADICTORY", "POSSIBLY_OUTDATED", None, None])
        self.assertEqual(rows[2]["assessment"]["update_evidence"]["quote"], modern)
        self.assertEqual(rows[0]["coverage"], "full_text")
        self.assertEqual(rows[0]["evidence"][0]["page"], 1)
        self.assertEqual(rows[3]["marker"], "[9]")
        self.assertIsNone(rows[3]["reference"])
        self.assertIn("Missing citation", rows[4]["review_reason"])
