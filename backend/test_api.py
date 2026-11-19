"""Deterministic API checks; no live provider requests or credentials needed."""
import unittest
from unittest.mock import patch, AsyncMock
import httpx
from fastapi.testclient import TestClient
from main import app
from integrations.providers import search_all

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health(self):
        response = self.client.get('/api/health')
        self.assertEqual(response.status_code, 200)
        self.assertIn('crossref', response.json()['providers'])

    def test_invalid_search(self):
        self.assertEqual(self.client.get('/api/evidence/search?q=a').status_code, 422)
        self.assertEqual(self.client.get('/api/evidence/search?q=learning&providers=wrong').status_code, 400)

    def test_open_access_timeout(self):
        with patch('main.unpaywall', new=AsyncMock(side_effect=httpx.ReadTimeout('timeout'))):
            response = self.client.get('/api/evidence/open-access?doi=10.1/test')
        self.assertEqual(response.status_code, 502)
        self.assertIn('retry', response.json()['detail'])

    def test_missing_configuration(self):
        with patch('main.unpaywall', new=AsyncMock(side_effect=ValueError('UNPAYWALL_EMAIL must be configured'))):
            self.assertEqual(self.client.get('/api/evidence/open-access?doi=10.1/test').status_code, 400)

class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_rate_limited_extraction_retains_citation(self):
        from app.database import init_db
        from app.pipeline import create_job, run_pipeline
        from app.providers import ExtractionProviderError
        from main import verify_claims, verify_report

        init_db()
        job = create_job('study.txt', 'text/plain')
        sentence = 'Active learning improves examination performance [1].'
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
