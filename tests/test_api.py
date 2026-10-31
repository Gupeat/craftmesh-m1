from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import make_server


BASE_PARAMS = {
    "wallThickness": 1.5, "undercutAngle": 3, "inlayGap": 0.2, "stoneHardness": 6,
    "engraveWidth": 0.3, "jointDepth": 8, "thickness": 20, "grainAngle": 0,
    "carveDepth": 1, "moisture": 8, "stoneDiameter": 2, "prongs": 4,
}


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.server = make_server("127.0.0.1", 0, Path(cls.tmp.name) / "test.db")
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def request(self, method, path, body=None):
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def create_order(self, **overrides):
        payload = {
            "patternId": "moon-gate", "process": "casting", "material": "brass",
            "finish": "polished", "quantity": 2, "params": BASE_PARAMS,
            "mode": "copy", "role": "designer",
        }
        payload.update(overrides)
        return self.request("POST", "/api/orders", payload)

    def test_health(self):
        status, body = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["service"], "craftmesh-m1")

    def test_bootstrap_has_ten_rules(self):
        status, body = self.request("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["patterns"]), 3)
        self.assertEqual(len(body["rules"]), 10)
        self.assertEqual(len(body["uses"]), 3)
        self.assertEqual(len(body["humanRules"]), 10)
        self.assertTrue(all(row["matched"] for row in body["humanRules"]))
        self.assertIn("quote", body["orders"][0]) if body["orders"] else None

    def test_check_returns_pass_and_fail(self):
        status, body = self.request("POST", "/api/check", {
            "patternId": "moon-gate", "process": "casting", "material": "brass",
            "finish": "polished", "quantity": 1, "params": BASE_PARAMS, "mode": "copy",
        })
        self.assertEqual(status, 200)
        self.assertTrue(body["result"]["ok"])
        self.assertEqual(body["result"]["checks"]["verdict"], "pass")

        bad = dict(BASE_PARAMS, wallThickness=0.5)
        status, body = self.request("POST", "/api/check", {
            "patternId": "moon-gate", "process": "casting", "material": "brass",
            "finish": "polished", "quantity": 1, "params": bad, "mode": "copy",
        })
        self.assertEqual(status, 200)
        self.assertFalse(body["result"]["ok"])
        self.assertTrue(body["result"]["checks"]["unmanufacturable"])

    def test_non_commercial_use_blocks_check_and_order(self):
        status, body = self.request("POST", "/api/check", {
            "patternId": "moon-gate", "process": "casting", "material": "brass",
            "finish": "polished", "quantity": 1, "params": BASE_PARAMS,
            "mode": "copy", "use": "internal",
        })
        self.assertEqual(status, 200)
        self.assertFalse(body["result"]["ok"])
        self.assertFalse(body["result"]["license"]["ok"])
        self.assertEqual(body["result"]["license"]["snapshot"]["use"], "internal")

        status, body = self.create_order(use="internal")
        self.assertEqual(status, 422, body)
        self.assertEqual(body["error"], "validation_failed")

    def test_create_and_lifecycle(self):
        status, body = self.create_order()
        self.assertEqual(status, 201, body)
        order = body["order"]
        oid = order["id"]
        self.assertEqual(order["status"], "draft")
        self.assertEqual(order["license"]["source"], "original")

        steps = [
            ("submit", "designer"), ("accept", "reviewer"), ("start_production", "ops"),
            ("send_to_qc", "ops"), ("pass_qc", "qc"), ("settle", "finance"),
        ]
        for action, role in steps:
            status, body = self.request("POST", f"/api/orders/{oid}/transition", {"action": action, "role": role})
            self.assertEqual(status, 200, body)
        status, body = self.request("GET", f"/api/orders/{oid}")
        self.assertEqual(status, 200)
        self.assertEqual(body["order"]["status"], "settled")
        self.assertEqual(len(body["order"]["audit"]), 7)

    def test_permission_and_invalid_state(self):
        status, body = self.create_order()
        oid = body["order"]["id"]
        status, body = self.request("POST", f"/api/orders/{oid}/transition", {"action": "submit", "role": "ops"})
        self.assertEqual(status, 403)
        status, body = self.request("POST", f"/api/orders/{oid}/transition", {"action": "accept", "role": "reviewer"})
        self.assertEqual(status, 409)

    def test_rework_requires_note(self):
        status, body = self.create_order()
        oid = body["order"]["id"]
        self.request("POST", f"/api/orders/{oid}/transition", {"action": "submit", "role": "designer"})
        status, body = self.request("POST", f"/api/orders/{oid}/transition", {"action": "request_rework", "role": "reviewer"})
        self.assertEqual(status, 422)
        self.assertEqual(body["error"], "note_required")

    def raw(self, path):
        req = urllib.request.Request(self.base + path, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def test_source_bundle_download(self):
        root = Path(__file__).resolve().parents[1]
        zip_path = root / "downloads" / "craftmesh-1724-source.zip"
        if not zip_path.is_file():
            self.skipTest("source bundle not built (run make_source_bundle.py)")
        status, body = self.raw("/downloads/craftmesh-1724-source.zip")
        self.assertEqual(status, 200)
        self.assertEqual(body[:2], b"PK")
        self.assertGreater(len(body), 100000)
        status, sha = self.raw("/downloads/craftmesh-1724-source.zip.sha256")
        self.assertEqual(status, 200)
        self.assertIn(hashlib.sha256(zip_path.read_bytes()).hexdigest().encode("ascii"), sha)
        for path in ("/downloads/../server.py", "/downloads/nope.zip"):
            status, body = self.raw(path)
            self.assertEqual(status, 404, path)

    def test_reset_requires_admin(self):
        status, body = self.request("POST", "/api/demo/reset", {"role": "designer"})
        self.assertEqual(status, 403)
        status, body = self.request("POST", "/api/demo/reset", {"role": "admin"})
        self.assertEqual(status, 200)
        self.assertTrue(body["reset"])

    def test_static_allowlist_blocks_source_and_db(self):
        status, body = self.raw("/")
        self.assertEqual(status, 200)
        self.assertIn(b"CraftMesh", body)
        status, body = self.raw("/app.js")
        self.assertEqual(status, 200)
        self.assertIn(b"/api/bootstrap", body)
        for path in ("/server.py", "/core.py", "/m1.db", "/tests/test_core.py"):
            status, body = self.raw(path)
            self.assertEqual(status, 404, path)
            self.assertIn(b"not_found", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
