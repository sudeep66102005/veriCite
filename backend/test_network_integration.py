import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app import database
from app.peers import quota_peer
from integrations.http import clear_cache, metadata_get
from main import app


class ProviderIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_transient_failure_then_cache_hit_and_credential_isolation(self):
        clear_cache()
        calls = []
        async def respond(request):
            calls.append(request.headers.get("authorization"))
            if len(calls) == 1:
                return httpx.Response(429, headers={"Retry-After": "0"})
            return httpx.Response(200, json={"count": len(calls)})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            url = "https://provider.example/works"
            for key, expected in [("a", 2), ("a", 2), ("b", 3)]:
                result = await metadata_get(client, url, headers={"Authorization": key})
                self.assertEqual(result.json()["count"], expected)
        self.assertEqual(calls, ["a", "a", "b"])


class VerificationIntegration(unittest.TestCase):
    def test_job_from_submission_to_private_report(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(database, "_DB", Path(directory) / "jobs.sqlite"), patch("main.GEMINI_API_KEY", "unused"), TestClient(app) as client:
            submitted = client.post("/api/verify", json={"text": "The telescope counted forty objects [9]."})
            self.assertEqual(submitted.status_code, 202, submitted.text)
            job = submitted.json()
            path = "/api/verify/" + job["job_id"]
            headers = {"Authorization": "Bearer " + job["access_token"]}
            self.assertEqual(client.get(path + "/report").status_code, 404)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                response = client.get(path + "/report", headers=headers)
                if response.status_code == 200:
                    break
                self.assertEqual(response.status_code, 409)
                time.sleep(.02)
            self.assertEqual(response.status_code, 200)
            [row] = response.json()["rows"]
            self.assertEqual(row["marker"], "[9]")
            self.assertEqual(row["mapping"], "unmatched")
            self.assertIsNone(row["assessment"])

    def test_forwarded_chain_stops_at_first_untrusted_hop(self):
        with patch.dict(os.environ, {"TRUSTED_PROXY_CIDRS": "10.0.0.0/8"}):
            chain = "192.0.2.99, 198.51.100.1, 10.0.0.2"
            self.assertEqual(quota_peer("10.0.0.1", chain), "198.51.100.1")
            self.assertEqual(quota_peer("203.0.113.10", chain), "203.0.113.10")
            self.assertEqual(quota_peer("10.0.0.1", "invalid"), "10.0.0.1")
