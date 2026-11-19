from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import httpx

from app.models import CoverageStatus, IdentityStatus, Reference
from app.resolution import resolve_reference
from app.retrieval import retrieve_source


TITLE = "Effects of active learning in university courses"
DOI = "10.1234/example"
PDF = "https://repository.example/work.pdf"


def reference(**fields):
    return Reference(ref_id="ref1", document_id="doc1", raw_entry=TITLE, **fields)


class VerificationProviderTests(IsolatedAsyncioTestCase):
    async def test_crossref_accepts_doi_only_and_rejects_metadata_conflict(self):
        def respond(request):
            if request.url.host == "api.crossref.org":
                return httpx.Response(200, json={"message": {"title": [TITLE], "DOI": DOI}})
            return httpx.Response(404)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            matched = await resolve_reference(reference(doi=f"https://doi.org/{DOI}"), client)
            mismatch = await resolve_reference(reference(doi=DOI, title="A different study"), client)
        self.assertEqual(matched.identity_status, IdentityStatus.matched)
        self.assertEqual(matched.canonical_doi, DOI)
        self.assertEqual(mismatch.identity_status, IdentityStatus.metadata_mismatch)

    async def test_openalex_title_fallback_ignores_wrong_candidate(self):
        def respond(request):
            if request.url.host == "api.crossref.org":
                return httpx.Response(429)
            self.assertEqual(request.url.params["search"], TITLE)
            return httpx.Response(200, json={"results": [
                {"title": "Unrelated paper"},
                {"id": "https://openalex.org/W1", "title": TITLE,
                 "doi": f"https://doi.org/{DOI}", "best_oa_location": {"pdf_url": PDF}},
            ]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            source = await resolve_reference(reference(title=TITLE), client)
        self.assertEqual(source.identity_status, IdentityStatus.matched)
        self.assertEqual(source.pdf_urls, [PDF])

    async def test_unpaywall_recovers_after_openalex_pdf_fails(self):
        def respond(request):
            urls.append(request.url.host)
            if request.url.host == "api.crossref.org":
                return httpx.Response(200, json={"message": {"title": [TITLE], "DOI": DOI}})
            if request.url.host == "api.openalex.org":
                return httpx.Response(200, json={"title": TITLE, "doi": DOI,
                    "best_oa_location": {"pdf_url": "https://publisher.example/unavailable.pdf"}})
            if request.url.host == "api.unpaywall.org":
                self.assertEqual(request.url.params["email"], "research@example.org")
                return httpx.Response(200, json={"doi": DOI, "best_oa_location": {"url_for_pdf": PDF}})
            if str(request.url) == PDF:
                return httpx.Response(200, headers={"Content-Type": "application/pdf"}, content=b"%PDF-1.7")
            return httpx.Response(404)

        urls = []
        with patch("app.resolution.UNPAYWALL_EMAIL", "research@example.org"), patch(
            "app.retrieval._parse_pdf", return_value=[("Observed improvement in the study.", "Results", 4, None)]
        ):
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                source = await resolve_reference(reference(doi=DOI), client)
                retrieved, passages = await retrieve_source(source, [], client)
        self.assertEqual(urls, ["api.crossref.org", "api.openalex.org",
                                "publisher.example", "api.unpaywall.org", "repository.example"])
        self.assertEqual(retrieved.coverage, CoverageStatus.full_text)
        self.assertEqual(retrieved.source_url, PDF)
        self.assertEqual(passages[0].page, 4)

    async def test_semantic_scholar_abstract_works_without_unpaywall(self):
        def respond(request):
            if request.url.host in {"api.crossref.org", "api.openalex.org"}:
                return httpx.Response(404)
            self.assertEqual(request.url.host, "api.semanticscholar.org")
            return httpx.Response(200, json={
                "paperId": "abc", "title": TITLE, "externalIds": {"DOI": DOI},
                "abstract": "The study tested active learning in undergraduate courses.",
            })

        with patch("app.resolution.UNPAYWALL_EMAIL", ""):
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                source = await resolve_reference(reference(title=TITLE, doi=DOI), client)
                retrieved, passages = await retrieve_source(source, [], client)
        self.assertEqual(retrieved.coverage, CoverageStatus.abstract_only)
        self.assertEqual(passages[0].section, "Abstract")
