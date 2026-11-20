"""Deterministic API checks; no live provider requests or credentials needed."""
import unittest
import os
from unittest.mock import patch, AsyncMock
import httpx
from integrations.http import clear_cache
from fastapi.testclient import TestClient
from main import app
from integrations.providers import core, search_all

class ApiTests(unittest.TestCase):
    def setUp(self):
        clear_cache()
        self.client = TestClient(app)

    def test_health(self):
        response = self.client.get('/api/health')
        self.assertEqual(response.status_code, 200)
        self.assertIn('crossref', response.json()['providers'])

    def test_invalid_search(self):
        self.assertEqual(self.client.get('/api/evidence/search?q=a').status_code, 422)
        self.assertEqual(self.client.get('/api/evidence/search?q=learning&providers=wrong').status_code, 400)

    def test_core_work_details(self):
        work = {"id": 267312, "title": "Study", "fullText": "Evidence from CORE"}
        request = httpx.Request("GET", "https://api.core.ac.uk/v3/works/267312")
        with patch.dict(os.environ, {"CORE_API_KEY": "test-key"}):
            with patch("httpx.AsyncClient.get", new=AsyncMock(
                return_value=httpx.Response(200, request=request, json=work)
            )) as get:
                response = self.client.get("/api/evidence/core/works/267312")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), work)
        get.assert_awaited_once_with(
            str(request.url), params=None,
            headers={"Authorization": "Bearer test-key", "Accept": "application/json"},
            follow_redirects=False,
        )

    def test_core_work_error_statuses(self):
        path = "/api/evidence/core/works/267312"
        self.assertEqual(self.client.get("/api/evidence/core/works/0").status_code, 422)
        with patch.dict(os.environ, {"CORE_API_KEY": ""}):
            self.assertEqual(self.client.get(path).status_code, 503)
        request = httpx.Request("GET", "https://api.core.ac.uk/v3/works/267312")
        with patch.dict(os.environ, {"CORE_API_KEY": "test-key"}):
            for upstream, expected in ((404, 404), (429, 429), (401, 502)):
                with self.subTest(upstream=upstream):
                    with patch("httpx.AsyncClient.get", new=AsyncMock(
                        return_value=httpx.Response(upstream, request=request)
                    )):
                        self.assertEqual(self.client.get(path).status_code, expected)

    def test_open_access_timeout(self):
        with patch('main.unpaywall', new=AsyncMock(side_effect=httpx.ReadTimeout('timeout'))):
            response = self.client.get('/api/evidence/open-access?doi=10.1/test')
        self.assertEqual(response.status_code, 502)
        self.assertIn('retry', response.json()['detail'])

    def test_missing_configuration(self):
        with patch('main.unpaywall', new=AsyncMock(side_effect=ValueError('UNPAYWALL_EMAIL must be configured'))):
            self.assertEqual(self.client.get('/api/evidence/open-access?doi=10.1/test').status_code, 400)

class ProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        clear_cache()

    async def test_rate_limited_extraction_retains_citation(self):
        from app.database import init_db
        from app.pipeline import create_job, run_pipeline
        from app.providers import ExtractionProviderError
        from main import verify_claims, verify_report

        init_db()
        job = create_job('study.txt', 'text/plain')
        sentence = 'Active learning improves examination performance and increases retention [1].'
        manuscript = f'Background.   {sentence}\n\nReferences\n\n[1] Freeman et al. (2014). Active learning increases student performance.'
        error = ExtractionProviderError('Gemini API request failed (HTTP 429).', stop_job_requests=True)
        with patch('app.extraction.extract_claims_gemini', new=AsyncMock(side_effect=error)):
            await run_pipeline(job.job_id, manuscript.encode(), 'study.txt', 'text/plain')
        report = await verify_report(job.job_id)
        self.assertEqual(report['total_claims'], 1)
        [row] = (await verify_claims(job.job_id))['rows']
        self.assertEqual(row['text'], sentence)
        self.assertEqual(row['marker'], '[1]')
        self.assertIn('Freeman', row['reference'])
        self.assertIn('429', row['extraction_error'])
        self.assertIsNone(row['assessment'])
        self.assertEqual(row['evidence'], [])

    async def test_core_search_auth_query_and_full_text_metadata(self):
        query = 'authors:"Yann LeCun" AND yearPublished>=2020'
        client = AsyncMock()
        client.get.return_value = httpx.Response(200, request=httpx.Request(
            "GET", "https://api.core.ac.uk/v3/search/works/"
        ), json={"results": [
            {"id": 123, "title": "Study", "authors": [{"name": "Yann LeCun"}],
             "yearPublished": 2021, "doi": "10.1234/example",
             "downloadUrl": "https://example.org/study.pdf"},
            {"id": 124, "title": "Metadata only", "fullText": "Not available for public API users."},
        ]})
        with patch.dict(os.environ, {"CORE_API_KEY": "test-key"}):
            papers = await core(client, query, 2)
        client.get.assert_awaited_once_with(
            "https://api.core.ac.uk/v3/search/works/",
            params={"q": query, "limit": 2},
            headers={"Authorization": "Bearer test-key", "Accept": "application/json"},
            follow_redirects=False,
        )
        self.assertEqual(papers[0]["authors"], ["Yann LeCun"])
        self.assertEqual(papers[0]["year"], 2021)
        self.assertEqual(papers[0]["open_access_pdf"], "https://example.org/study.pdf")
        self.assertTrue(papers[0]["has_full_text"])
        self.assertFalse(papers[1]["has_full_text"])

    async def test_core_only_search_requires_a_key(self):
        with patch.dict(os.environ, {"CORE_API_KEY": ""}):
            with self.assertRaisesRegex(ValueError, "CORE_API_KEY"):
                await search_all('learning', providers=['core'])

    async def test_partial_success_and_safe_errors(self):
        good = AsyncMock(return_value=[{'title':'Study','doi':'10.1/test'}])
        bad = AsyncMock(side_effect=httpx.ConnectError('URL contains api_key=secret'))
        with patch.dict('integrations.providers.SEARCH_PROVIDERS', {'good':good,'bad':bad}, clear=True):
            result = await search_all('learning', providers=['good','bad'])
        self.assertEqual(len(result['papers']),1)
        self.assertIn('bad',result['provider_errors'])
        self.assertNotIn('secret',str(result))

if __name__ == '__main__':
    unittest.main()
