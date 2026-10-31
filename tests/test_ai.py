"""模块 B · 企业 AI 服务层单元测试（本地规则引擎，双行业）。

运行：
  python -m unittest tests.test_ai -v

测试使用临时 SQLite（mod_ai.set_store_path），不会改动 data/ai.db。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import mod_ai  # noqa: E402


class AiModuleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="ai-test-")
        mod_ai.set_store_path(Path(cls.tmp.name) / "ai-test.db")

    @classmethod
    def tearDownClass(cls):
        mod_ai.set_store_path(None)
        cls.tmp.cleanup()

    def setUp(self):
        mod_ai.set_store_path(Path(self.tmp.name) / "ai-test.db")
        mod_ai.reset_demo("admin")
        mod_ai.switch_industry("woodcraft", "admin")

    # ---------------------------------------------------------------- config
    def test_config_has_two_industries_and_permissions(self):
        cfg = mod_ai.get_config()
        self.assertEqual(cfg["module"], "ai")
        ids = [item["id"] for item in cfg["industries"]]
        self.assertEqual(sorted(ids), ["jewelry", "woodcraft"])
        self.assertEqual(len(cfg["workflowTemplates"]), 2)
        self.assertIn("agent.chat", cfg["permissions"])
        self.assertIn("admin", cfg["permissions"]["agent.chat"]["allowedRoles"])
        self.assertNotIn("workshop", cfg["permissions"]["agent.chat"]["allowedRoles"])
        self.assertIn("本地", cfg["engine"]["disclosure"])
        self.assertTrue(cfg["sampleData"])

    def test_seed_knowledge_documents(self):
        res = mod_ai.list_knowledge()
        self.assertEqual(res["industry"], "woodcraft")
        self.assertGreaterEqual(res["counts"]["total"], 4)
        self.assertGreaterEqual(res["counts"]["published"], 4)
        self.assertGreaterEqual(res["counts"]["chunks"], 12)
        for doc in res["documents"]:
            self.assertEqual(doc["status"], "published")
            self.assertGreaterEqual(doc["chunkCount"], 1)
        detail = mod_ai.get_knowledge(res["documents"][0]["id"])
        self.assertGreaterEqual(len(detail["document"]["chunks"]), 1)
        self.assertEqual(detail["document"]["chunks"][0]["index"], 1)

    # ---------------------------------------------------------------- search
    def test_search_returns_doc_chunk_citations(self):
        res = mod_ai.search_knowledge("户外木作含水率控制在多少", top_k=3)
        self.assertGreaterEqual(res["count"], 1)
        self.assertLessEqual(res["count"], 3)
        self.assertGreaterEqual(res["scanned"]["chunks"], 12)
        for hit in res["hits"]:
            self.assertIn("#c", hit["citation"])
            self.assertGreater(hit["score"], 0)
            self.assertTrue(hit["docTitle"])
            self.assertTrue(hit["text"])

    def test_industry_switch_changes_knowledge_and_site(self):
        wood_site = mod_ai.get_site("zh")
        res = mod_ai.switch_industry("jewelry", "ops")
        self.assertEqual(res["industry"]["id"], "jewelry")
        self.assertEqual(mod_ai.list_knowledge()["industry"], "jewelry")
        jewelry_site = mod_ai.get_site("zh")
        self.assertNotEqual(wood_site["site"]["title"], jewelry_site["site"]["title"])
        self.assertIn("珠宝", jewelry_site["site"]["title"])
        mod_ai.switch_industry("woodcraft", "ops")
        self.assertEqual(mod_ai.list_knowledge()["industry"], "woodcraft")

    # ----------------------------------------------------------------- agent
    def test_agent_knowledge_intent_uses_search_tool(self):
        session = mod_ai.create_session({"title": "测试会话"})
        result = mod_ai.send_session_message(
            session["id"], {"content": "户外木作含水率要控制在多少？"}
        )
        self.assertEqual(result["intent"], "search_knowledge")
        self.assertEqual(result["intentLabel"], "知识库检索")
        tool_names = [call["tool"] for call in result["toolCalls"]]
        self.assertIn("search_knowledge", tool_names)
        self.assertGreaterEqual(len(result["citations"]), 1)
        self.assertIn("#c", result["citations"][0]["citation"])
        self.assertTrue("8%" in result["reply"] or "10%" in result["reply"])
        self.assertEqual(result["engine"], "本地规则引擎")
        history = mod_ai.get_session(session["id"])
        self.assertGreaterEqual(len(history["messages"]), 2)

    def test_agent_lead_intent_writes_crm(self):
        before = mod_ai.list_leads()["total"]
        session = mod_ai.create_session({"title": "留资会话"})
        result = mod_ai.send_session_message(
            session["id"],
            {"content": "我是林女士，邮箱 lin-test@example.com，预算 20 万，想做黑胡桃餐桌，请联系我。"},
        )
        self.assertEqual(result["intent"], "create_lead")
        self.assertIn("create_lead", [call["tool"] for call in result["toolCalls"]])
        leads = mod_ai.list_leads()
        self.assertEqual(leads["total"], before + 1)
        lead = leads["leads"][0]
        self.assertEqual(lead["email"], "lin-test@example.com")
        self.assertEqual(lead["stage"], "new")

    def test_agent_lead_without_intent_verb_extracts_product(self):
        session = mod_ai.create_session({"title": "自然询盘解析"})
        result = mod_ai.send_session_message(
            session["id"],
            {"content": "请记录：王女士 wang2@example.com，预算 12 万，黑胡桃餐桌，来自日本"},
        )
        self.assertEqual(result["intent"], "create_lead")
        call = result["toolCalls"][0]
        self.assertTrue(call["ok"], call)
        self.assertEqual(call["args"]["name"], "王女士")
        self.assertIn("黑胡桃", call["args"]["interest"])
        self.assertEqual(call["args"]["country"], "JP")

    # ------------------------------------------------------------- workflows
    def _first_template(self):
        return mod_ai.get_config()["workflowTemplates"][0]

    def test_workflow_success_run(self):
        tpl = self._first_template()
        workflow = mod_ai.create_workflow({"templateId": tpl["id"], "name": "测试询盘分诊"})
        self.assertEqual(workflow["id"][:3], "wf-")
        self.assertEqual(workflow["status"], "draft")
        run = mod_ai.run_workflow(workflow["id"], {"input": tpl["inputExample"]})
        self.assertEqual(run["status"], "success")
        self.assertEqual(len(run["steps"]), 7)
        self.assertTrue(all(step["ok"] for step in run["steps"]))
        self.assertTrue(run["leadId"].startswith("lead-"))
        self.assertTrue(run["quoteId"].startswith("quote-"))
        self.assertEqual(run["grade"], "A")
        refreshed = mod_ai.get_workflow(workflow["id"])
        self.assertEqual(refreshed["status"], "active")
        self.assertEqual(refreshed["runCount"], 1)
        self.assertGreaterEqual(len(mod_ai.list_runs(workflow["id"])["runs"]), 1)

    def test_workflow_retry_after_failed_run(self):
        tpl = self._first_template()
        workflow = mod_ai.create_workflow({"templateId": tpl["id"], "name": "测试失败重试"})
        failed = mod_ai.run_workflow(
            workflow["id"], {"input": {"name": "王先生", "interest": "黑胡桃餐桌"}}
        )
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["failedStep"]["index"], 1)
        retried = mod_ai.retry_run(failed["id"], {"input": tpl["inputExample"]})
        self.assertEqual(retried["status"], "success")
        self.assertEqual(retried["attempt"], 2)
        self.assertEqual(retried["retryOf"], failed["id"])
        self.assertNotEqual(retried["id"], failed["id"])

    def test_retry_rejects_successful_run(self):
        tpl = self._first_template()
        workflow = mod_ai.create_workflow({"templateId": tpl["id"]})
        run = mod_ai.run_workflow(workflow["id"], {"input": tpl["inputExample"]})
        self.assertEqual(run["status"], "success")
        with self.assertRaises(mod_ai.AIError) as ctx:
            mod_ai.retry_run(run["id"], {"input": tpl["inputExample"]})
        self.assertEqual(ctx.exception.status, 409)

    # ------------------------------------------------------------------ CRM
    def test_inquiry_validation_and_create(self):
        valid = {
            "name": "周先生",
            "email": "zhou-test@example.com",
            "country": "CN",
            "budget": "8 万",
            "interest": "黑胡桃户外餐桌",
            "message": "希望 11 月上门复尺（测试）",
            "lang": "zh",
        }
        created = mod_ai.create_inquiry(valid)
        lead = created["lead"]
        self.assertEqual(lead["stage"], "new")
        self.assertEqual(lead["source"], "inquiry-form")
        with self.assertRaises(mod_ai.AIError) as ctx:
            mod_ai.create_inquiry(dict(valid, email="not-an-email"))
        self.assertEqual(ctx.exception.status, 422)
        self.assertIn("邮箱", ctx.exception.message)
        with self.assertRaises(mod_ai.AIError) as ctx2:
            mod_ai.create_inquiry({"email": "a@example.com"})
        self.assertEqual(ctx2.exception.status, 422)

    def test_lead_stage_advance_writes_history(self):
        lead = mod_ai.create_inquiry({
            "name": "陈先生",
            "email": "chen-test@example.com",
            "country": "CN",
            "budget": "60000",
            "interest": "白蜡木书柜",
            "lang": "zh",
        })["lead"]
        updated = mod_ai.update_lead(lead["id"], {"stage": "contacted", "note": "电话已联系"})
        self.assertEqual(updated["stage"], "contacted")
        self.assertGreaterEqual(len(updated["history"]), 1)
        self.assertEqual(updated["history"][-1]["to"], "contacted")
        with self.assertRaises(mod_ai.AIError):
            mod_ai.update_lead(lead["id"], {"stage": "not-a-stage"})

    # ------------------------------------------------------------- site / SEO
    def test_site_three_languages_and_seo(self):
        titles = []
        for lang in ("zh", "en", "ja"):
            data = mod_ai.get_site(lang)
            self.assertEqual(data["lang"], lang)
            titles.append(data["site"]["title"])
            seo = data["seo"]
            self.assertEqual(len(seo["checks"]), 8)
            self.assertGreaterEqual(seo["coverage"]["pct"], 80)
            self.assertTrue(all(check["ok"] for check in seo["checks"]))
            self.assertTrue(seo["meta"]["robots"].startswith("noindex,nofollow"))
        self.assertEqual(len(set(titles)), 3)
        seo_res = mod_ai.get_seo("ja")
        self.assertEqual(seo_res["seo"]["meta"]["title"], titles[2])
        with self.assertRaises(mod_ai.AIError):
            mod_ai.get_site("fr")

    def test_fde_handbook_markdown(self):
        data = mod_ai.get_fde_handbook()
        self.assertGreaterEqual(data["chars"], 3000)
        self.assertGreaterEqual(data["sections"], 8)
        self.assertIn("访谈", "".join(data["headings"]))
        self.assertIn("##", data["markdown"])

    # --------------------------------------------------------------- 权限 / 重置
    def test_permission_denied_for_workshop(self):
        with self.assertRaises(mod_ai.AIError) as ctx:
            mod_ai.create_workflow({"templateId": "wf-wd-inquiry"}, "workshop")
        self.assertEqual(ctx.exception.status, 403)
        with self.assertRaises(mod_ai.AIError) as ctx2:
            mod_ai.create_inquiry({
                "name": "越权", "email": "x@example.com", "interest": "x"
            }, "workshop")
        self.assertEqual(ctx2.exception.status, 403)
        cfg = mod_ai.get_config(role="workshop")
        self.assertFalse(cfg["permissions"]["workflow.write"]["allowed"])

    def test_reset_demo_restores_seed(self):
        mod_ai.create_inquiry({
            "name": "临时", "email": "tmp@example.com", "interest": "临时需求"
        })
        mod_ai.create_workflow({"templateId": "wf-wd-inquiry"})
        mod_ai.create_session({"title": "临时会话"})
        reset = mod_ai.reset_demo("admin")
        self.assertTrue(reset["reset"])
        counts = reset["counts"]
        self.assertGreaterEqual(counts["documents"], 4)
        self.assertGreaterEqual(counts["chunks"], 12)
        dash = mod_ai.dashboard()
        self.assertEqual(dash["leads"]["total"], 0)
        self.assertEqual(dash["workflows"]["instances"], 0)
        self.assertEqual(dash["sessions"]["total"], 0)
        self.assertEqual(dash["workflows"]["templates"], 2)

    def test_dashboard_counts_consistency(self):
        dash = mod_ai.dashboard()
        self.assertGreaterEqual(dash["knowledge"]["documents"], 4)
        self.assertGreaterEqual(dash["knowledge"]["chunks"], 12)
        self.assertEqual(dash["workflows"]["templates"], 2)
        self.assertEqual(dash["siteLanguages"], 3)
        self.assertEqual(dash["engine"]["id"], "local-rules")

    def test_scenario_chain(self):
        result = mod_ai.run_scenario("admin")
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(len(result["steps"]), 12)
        summary = result["summary"]
        self.assertEqual(summary["steps"], 17)
        self.assertEqual(summary["steps"], len(result["steps"]))
        self.assertEqual(summary["expectedFailures"], 2)
        self.assertEqual(summary["engine"], "本地规则引擎")
        self.assertEqual(summary["siteLanguages"], ["zh", "en", "ja"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
