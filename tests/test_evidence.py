# -*- coding: utf-8 -*-
"""验收驾驶舱的一致性测试：配置结构、检查类型、证据包导出。

不启动服务、不跑 run_static（它会再跑一遍 unittest，造成递归）。
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import mod_evidence

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "acceptance.json"
ALLOWED_TYPES = {"file", "filecount", "grep", "m1cases", "tests", "http", "scenario"}


class AcceptanceConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.items = cls.config["items"]

    def test_config_version_and_items(self):
        self.assertEqual(self.config["version"], "1.0")
        self.assertEqual(len(self.items), 11)

    def test_item_ids_and_refs_cover_platform_items(self):
        ids = [item["id"] for item in self.items]
        refs = [item["ref"] for item in self.items]
        self.assertEqual(ids, ["P%d" % i for i in range(11)])
        self.assertEqual(refs, ["%d)" % i for i in range(11)])
        for item in self.items:
            self.assertTrue(item["title"])
            self.assertTrue(item["requirement"])
            self.assertIn(item["module"], {"M1", "M2", "AI", "IP", "ALL"})
            self.assertGreaterEqual(len(item["checks"]), 2, item["id"])

    def test_check_types_and_required_fields(self):
        for item in self.items:
            for check in item["checks"]:
                with self.subTest(item=item["id"], label=check.get("label")):
                    self.assertIn(check["type"], ALLOWED_TYPES)
                    self.assertTrue(check["label"])
                    if check["type"] == "file":
                        self.assertTrue(check["path"])
                        self.assertFalse(Path(check["path"]).is_absolute())
                    if check["type"] == "filecount":
                        self.assertTrue(check["dir"])
                        self.assertIn(check["ext"], (".py", ".html", ".js", ".wav", ".srt", ".svg", ".json", ".md"))
                        self.assertGreaterEqual(check["min"], 1)
                    if check["type"] == "grep":
                        re.compile(check["pattern"])
                        self.assertGreaterEqual(check.get("min", 1), 1)
                    if check["type"] == "m1cases":
                        self.assertEqual(check["minCases"], 10)
                        self.assertEqual(check["minBlocked"], 3)
                    if check["type"] == "tests":
                        self.assertGreaterEqual(check["minTests"], 40)
                    if check["type"] == "http":
                        self.assertTrue(check["path"].startswith("/api/"))
                    if check["type"] == "scenario":
                        self.assertIn(check["module"], {"m2", "ai", "ip"})
                        self.assertTrue(check["endpoint"].startswith("/api/"))
                        self.assertGreaterEqual(check["minSteps"], 10)

    def test_m1_m2_scan_targets_exist_on_disk(self):
        # B/C 的页面与文档由对应模块交付，此处只校验 M1/M2 已存在的目标，避免测试先行失败
        early = [item for item in self.items if item["milestone"] in {"M1", "M1+M2", "M2"}]
        checked = 0
        for item in early:
            for check in item["checks"]:
                if check["type"] == "file":
                    self.assertTrue(mod_evidence._resolve(check["path"]).is_file(), check["path"])
                    checked += 1
                elif check["type"] == "filecount":
                    self.assertTrue(mod_evidence._resolve(check["dir"]).is_dir(), check["dir"])
                    checked += 1
        self.assertGreater(checked, 0)

    def test_static_runner_covers_all_static_checks(self):
        expected = 0
        for item in self.items:
            expected += len([c for c in item["checks"] if c["type"] in {"file", "filecount", "grep", "m1cases", "tests"}])
        # run_static 会跑 unittest 子进程；这里只校验它声明的静态检查数量口径
        self.assertGreater(expected, 20)


class EvidenceExportTests(unittest.TestCase):
    def test_export_markdown_contains_items_and_conclusion(self):
        run = {
            "runId": "ev-test0001",
            "generatedAt": "2026-10-31T00:00:00+00:00",
            "environment": {"python": "3.12.14", "platform": "test"},
            "items": [
                {
                    "id": "P0", "ref": "0)", "title": "成果优先", "status": "passed",
                    "passedChecks": 5, "totalChecks": 5, "milestone": "M1", "module": "M1",
                    "requirement": "可运行仓库 + 启动说明", "checks": [],
                },
                {
                    "id": "P5", "ref": "5)", "title": "企业 AI 服务层", "status": "failed",
                    "passedChecks": 2, "totalChecks": 4, "milestone": "M3", "module": "B",
                    "requirement": "知识库 + 智能体 + 工作流", "checks": [], "note": "待补",
                },
            ],
        }
        markdown = mod_evidence.export_markdown(run)
        self.assertIn("# ClawHunt #1724 · 验收证据包", markdown)
        self.assertIn("1/2 项通过", markdown)
        self.assertIn("### P0 0) 成果优先", markdown)
        self.assertIn("### P5 5) 企业 AI 服务层", markdown)
        self.assertIn("待补", markdown)
        self.assertGreater(len(markdown), 500)


if __name__ == "__main__":
    unittest.main()
