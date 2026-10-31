"""Module C · 文化 IP 短剧管线单元测试。

运行：
  python -m unittest tests.test_ip -v
或：
  python tests/test_ip.py

测试使用临时 SQLite 数据目录，不会修改 data/ip.db；媒体文件为仓库内真实生成资产。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import mod_ip  # noqa: E402


class IpModuleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="ip-test-")
        cls.orig_data_dir = mod_ip.DATA_DIR
        cls.orig_db_path = mod_ip.DB_PATH
        cls.orig_store = mod_ip._store
        mod_ip.DATA_DIR = Path(cls.tmp.name)
        mod_ip.DB_PATH = mod_ip.DATA_DIR / "ip-test.db"
        mod_ip._store = None

    @classmethod
    def tearDownClass(cls):
        mod_ip._store = None
        mod_ip.DATA_DIR = cls.orig_data_dir
        mod_ip.DB_PATH = cls.orig_db_path
        mod_ip._store = cls.orig_store
        cls.tmp.cleanup()

    def setUp(self):
        mod_ip.reset_demo()

    def test_config_has_two_characters_and_complete_story(self):
        cfg = mod_ip.config()
        self.assertEqual([c["name"] for c in cfg["characters"]], ["远视", "远听"])
        self.assertEqual(len(cfg["story"]["beats"]), 6)
        self.assertEqual(len(cfg["shots"]), 12)
        self.assertEqual(len(cfg["review"]["rules"]), 9)
        self.assertEqual(len(cfg["license"]["clauses"]), 12)
        self.assertEqual(len(cfg["derivatives"]["skus"]), 6)
        self.assertEqual(cfg["module"]["title"], "山谷回声")
        for char in cfg["characters"]:
            for key in ("setting", "motifs", "personality", "voice", "can", "cannot", "portrait"):
                self.assertTrue(char.get(key), f"{char['name']} 缺少 {key}")

    def test_duration_is_within_30_to_45_seconds(self):
        report = mod_ip.duration_report()
        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["totalMs"], 40400)
        self.assertEqual(report["shotCount"], 12)
        self.assertGreaterEqual(report["totalMs"], 30000)
        self.assertLessEqual(report["totalMs"], 45000)

    def test_story_payload_fields_and_continuous_timeline(self):
        data = mod_ip.story_payload()
        self.assertEqual(len(data["shots"]), 12)
        self.assertEqual(data["fieldIssues"], [])
        expected = 0
        for shot in data["shots"]:
            self.assertEqual(shot["startMs"], expected)
            expected = shot["endMs"]
            self.assertTrue(shot["caption"])
            self.assertTrue(shot["svg"].startswith("/media/scenes/"))
        self.assertEqual(data["duration"]["totalMs"], expected)

    def test_asset_catalog_has_real_wav_svg_srt(self):
        catalog = mod_ip.asset_catalog()
        self.assertEqual(catalog["summary"]["total"], 41)
        self.assertEqual(catalog["summary"]["missing"], 0)
        self.assertTrue(all(check["ok"] for check in catalog["checks"]), catalog["checks"])
        voices = [a for a in catalog["assets"] if a["kind"] == "voice"]
        self.assertEqual(len(voices), 12)
        for asset in voices:
            self.assertEqual(asset["sampleRate"], 22050)
            self.assertTrue(asset["fitsSlot"], asset["label"])
            self.assertGreater(asset["bytes"], 0)
        scenes = [a for a in catalog["assets"] if a["kind"] == "scene"]
        self.assertEqual(len(scenes), 12)
        self.assertTrue(all(a["exists"] for a in scenes))

    def test_manifest_has_12_shots_and_master_wav(self):
        manifest = mod_ip.build_manifest()
        self.assertEqual(manifest["shotCount"], 12)
        self.assertEqual(manifest["totalMs"], 40400)
        self.assertTrue(manifest["durationOk"])
        self.assertEqual(manifest["master"]["durationMs"], 40400)
        self.assertEqual(manifest["master"]["sampleRate"], 22050)
        self.assertEqual(manifest["master"]["srtCues"], 12)
        self.assertTrue(manifest["allAudioFits"])
        self.assertTrue(manifest["assetsOk"])
        self.assertEqual(manifest["shots"][0]["startMs"], 0)
        self.assertEqual(manifest["shots"][-1]["endMs"], 40400)

    def test_review_pass_is_persisted(self):
        cfg = mod_ip.config()
        result = mod_ip.review_text(cfg["review"]["samples"]["pass"], "合规测试", "ops")
        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["findings"], [])
        self.assertTrue(result["reviewId"].startswith("review-"))
        rows = mod_ip.reviews_payload()
        self.assertEqual(rows["total"], 1)
        self.assertEqual(rows["counts"]["pass"], 1)

    def test_review_reject_finds_blockers(self):
        cfg = mod_ip.config()
        result = mod_ip.review_text(cfg["review"]["samples"]["reject"], "违规测试", "ops")
        self.assertEqual(result["verdict"], "reject")
        rules = {item["rule"] for item in result["findings"]}
        self.assertIn("real_person", rules)
        self.assertIn("medical_claim", rules)
        self.assertGreaterEqual(result["counts"]["blockers"], 1)
        self.assertEqual(mod_ip.reviews_payload()["counts"]["reject"], 1)

    def test_review_short_text_is_rejected_with_422(self):
        with self.assertRaises(mod_ip.IpError) as ctx:
            mod_ip.review_text("短", "太短", "ops")
        self.assertEqual(ctx.exception.status, 422)
        self.assertEqual(ctx.exception.error, "text_too_short")
        self.assertEqual(mod_ip.reviews_payload()["total"], 0)

    def test_review_role_without_permission_is_forbidden(self):
        with self.assertRaises(mod_ip.IpError) as ctx:
            mod_ip.review_text("这是一条越权审核测试文案。", "越权", "workshop")
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.error, "forbidden")
        self.assertIn("不能执行 内容审核", ctx.exception.message)
        self.assertIn("ops", ctx.exception.extra["allowedRoles"])

    def test_license_preview_generates_12_clauses(self):
        draft = mod_ip.license_preview({
            "licensee": "合成样例品牌（测试）",
            "purpose": "品牌短片",
            "territory": "中国大陆",
            "term": 12,
        }, "finance")
        self.assertEqual(draft["clauseCount"], 12)
        self.assertEqual(draft["status"], "draft")
        self.assertIn("模板样例", draft["notice"])
        self.assertIn("不构成法律意见", draft["disclaimer"])
        self.assertIn("合成样例品牌（测试）", draft["clauses"][0]["text"])
        self.assertEqual(mod_ip.licenses_payload()["total"], 1)

    def test_license_invalid_term_is_422(self):
        with self.assertRaises(mod_ip.IpError) as ctx:
            mod_ip.license_preview({
                "licensee": "合成样例品牌（测试）",
                "purpose": "品牌短片",
                "territory": "中国大陆",
                "term": 0,
            }, "finance")
        self.assertEqual(ctx.exception.status, 422)
        self.assertEqual(ctx.exception.error, "term_invalid")

    def test_asset_validation_detects_missing_wav(self):
        ok = mod_ip.validate_assets(role="admin")
        self.assertEqual(ok["timelineMs"], 40400)
        self.assertEqual(ok["masterAudioMs"], 40400)
        with self.assertRaises(mod_ip.IpError) as ctx:
            mod_ip.validate_assets(role="admin", simulate_missing_audio=True)
        self.assertEqual(ctx.exception.status, 422)
        self.assertEqual(ctx.exception.error, "asset_missing")
        self.assertIn("media/voice/shot-01.wav", ctx.exception.extra["missing"])

    def test_reset_clears_ledger_but_keeps_media(self):
        mod_ip.review_text("《山谷回声》为原创纸影短剧，已获授权用于合成样例演示。", "重置测试", "ops")
        mod_ip.license_preview({
            "licensee": "重置测试品牌",
            "purpose": "社交传播",
            "territory": "大中华区",
            "term": 6,
        }, "admin")
        before = mod_ip.dashboard()
        self.assertGreaterEqual(before["reviews"]["total"], 1)
        self.assertGreaterEqual(before["licenses"], 1)
        cleared = mod_ip.reset_demo()
        self.assertGreaterEqual(cleared["total"], 2)
        self.assertEqual(mod_ip.reviews_payload()["total"], 0)
        self.assertEqual(mod_ip.licenses_payload()["total"], 0)
        self.assertTrue(mod_ip.build_manifest()["assetsOk"])

    def test_full_scenario_passes_16_steps_with_two_expected_errors(self):
        result = mod_ip.run_scenario()
        self.assertEqual(result["scenario"], "ip-full-chain")
        self.assertEqual(result["summary"]["steps"], 16)
        self.assertEqual(result["summary"]["passed"], 16)
        self.assertEqual(result["summary"]["expectedFailures"], 2)
        self.assertEqual(result["summary"]["unexpected"], 0)
        self.assertTrue(result["summary"]["durationOk"])
        expected = [step for step in result["steps"] if step.get("expectError")]
        self.assertEqual(len(expected), 2)
        self.assertTrue(all(step.get("satisfied") for step in expected))
        self.assertEqual([step["status"] for step in expected], [403, 422])
        self.assertEqual(expected[0]["error"], "forbidden")
        self.assertEqual(expected[1]["error"], "asset_missing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
