import base64
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError

from scripts.evidence.tradier_raw_chain import NoRedirect, capture, write_evidence


class Response:
    status = 200

    def __init__(self, raw, url):
        self.raw, self.url = raw, url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def geturl(self):
        return self.url

    def read(self):
        return self.raw


class CaptureTests(unittest.TestCase):
    def collect(self, payload):
        raw = json.dumps(payload).encode()

        def opener(request, timeout):
            self.assertEqual(timeout, 30)
            self.assertTrue(request.full_url.startswith("https://api.tradier.com/v1/markets/options/chains?"))
            self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
            return Response(raw, request.full_url)

        return capture("SPY", "2026-10-16", "after-close", "test-token", opener), raw

    def test_lossless_rows_zeros_missing_and_raw_timestamps(self):
        rows = [
            {"symbol": "A", "bid": 0, "ask": 0, "last": 0, "volume": 0,
             "open_interest": 0, "bid_date": 0, "ask_date": 1723456789123, "trade_date": None},
            {"symbol": "B", "bid": 0, "ask": 2.5, "last": 1.2, "bid_date": "provider-value"},
            {"symbol": "C", "last": 0},
        ]
        result, raw = self.collect({"options": {"option": rows}, "extra": "retained"})
        self.assertEqual(result["payload"]["options"]["option"], rows)
        self.assertEqual(base64.b64decode(result["raw_payload_base64"]), raw)
        self.assertEqual(result["row_count"], 3)
        self.assertEqual(result["field_presence_counts"]["bid"], 2)
        self.assertNotIn("ask", result["payload"]["options"]["option"][2])
        self.assertNotIn("test-token", json.dumps(result))

    def test_single_row_and_explicit_empty_chain(self):
        self.assertEqual(self.collect({"options": {"option": {"bid": 0}}})[0]["row_count"], 1)
        self.assertEqual(self.collect({"options": {"option": None}})[0]["row_count"], 0)

    def test_provider_error_not_evidence(self):
        def failure(request, timeout):
            raise HTTPError(request.full_url, 403, "Forbidden", {}, None)

        with self.assertRaises(HTTPError):
            capture("SPY", "2026-10-16", "premarket", "test-token", failure)
        for payload in ({"error": "bad request"}, {"options": {}}, {"options": {"option": [None]}}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.collect(payload)

    def test_redirect_refused(self):
        with self.assertRaises(ValueError):
            NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other.example")

        def redirect(request, timeout):
            return Response(b'{"options":{"option":null}}', "https://sandbox.tradier.com/")

        with self.assertRaises(ValueError):
            capture("SPY", "2026-10-16", "premarket", "test-token", redirect)

    def test_atomic_private_write_and_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "capture.json"
            write_evidence(output, {"raw": 0})
            self.assertEqual(json.loads(output.read_text()), {"raw": 0})
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                write_evidence(output, {"raw": 99})
            self.assertEqual(json.loads(output.read_text()), {"raw": 0})
            self.assertEqual(list(Path(directory).iterdir()), [output])


if __name__ == "__main__":
    unittest.main()
