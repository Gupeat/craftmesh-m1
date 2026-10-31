# -*- coding: utf-8 -*-
"""M2 C2M 预售与制造协同的单元测试（直接调用业务函数，覆盖规则与账目）。

只使用临时 SQLite 文件，不改动 data/m2.db；全部数据为合成样例。
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import core
import mod_m2


def campaign_payload(**overrides):
    payload = {
        "patternId": "moon-gate",
        "process": "casting",
        "material": "brass",
        "finish": "polished",
        "quantityPerUnit": 1,
        "deadlineDays": 14,
        "use": "commercial",
    }
    payload.update(overrides)
    return payload


class M2Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_data_dir = mod_m2.DATA_DIR
        cls._tmp = tempfile.mkdtemp(prefix="craftmesh-m2-test-")
        mod_m2.DATA_DIR = Path(cls._tmp)
        mod_m2._store = None

    @classmethod
    def tearDownClass(cls):
        mod_m2._store = None
        mod_m2.DATA_DIR = cls._orig_data_dir
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self):
        mod_m2.reset_demo()

    # ---- 便捷构造 ---------------------------------------------------------
    def open_campaign(self, **overrides):
        campaign = mod_m2.create_campaign(campaign_payload(**overrides), "admin")
        return mod_m2.open_campaign(campaign["id"], "admin")

    def funded_order(self, qty=20, **overrides):
        campaign = self.open_campaign(**overrides)
        result = mod_m2.create_pledge(campaign["id"], {"backer": "测试支持者", "qty": qty}, "buyer")
        self.assertTrue(result["funded"])
        return campaign, result["campaign"], mod_m2._order(result["campaign"]["productionOrderId"])

    def accepted_order(self, qty=20, workshop="ws-jewel-01", **overrides):
        _, _, order = self.funded_order(qty=qty, **overrides)
        dispatch = mod_m2.dispatch_order(order["id"], {"workshopId": workshop, "dimensionMm": 60}, "admin")["dispatch"]
        mod_m2.respond_dispatch(dispatch["id"], {"accept": True, "note": "接单"}, "workshop")
        mod_m2.start_order(order["id"], "workshop")
        return mod_m2._order(order["id"])

    def shipped_order(self, **overrides):
        order = self.accepted_order(**overrides)
        mod_m2.submit_qc(order["id"], "ops")
        mod_m2.qc_result(order["id"], {"result": "pass", "note": "外观与尺寸通过"}, "admin")
        mod_m2.ship_order(order["id"], {"carrier": "合成物流", "trackingNo": "SYN-0001"}, "admin")
        return mod_m2._order(order["id"])


class CampaignTests(M2Base):
    def test_quote_and_deposit_are_computed_server_side(self):
        campaign = mod_m2.create_campaign(campaign_payload(), "admin")
        quote_row = core.quote("casting", 1)
        self.assertEqual(campaign["unitCents"], quote_row["unitCents"])
        self.assertEqual(campaign["minBatch"], 20)
        self.assertEqual(campaign["depositCentsPerUnit"], round(quote_row["unitCents"] * 1 * 0.3))
        self.assertEqual(campaign["status"], "draft")
        self.assertTrue(campaign["licenseSnapshot"]["checkedAt"])
        self.assertEqual(campaign["params"], core.normalize_params({}))

    def test_license_scope_violation_is_rejected(self):
        # wave-lattice 只授权 commercial；内部使用应被拒绝
        with self.assertRaises(mod_m2.M2Error) as ctx:
            mod_m2.create_campaign(campaign_payload(patternId="wave-lattice", use="internal"), "admin")
        self.assertEqual(ctx.exception.status, 422)
        self.assertEqual(ctx.exception.error, "license_denied")
        self.assertTrue(ctx.exception.extra["errors"])

    def test_unknown_process_is_rejected(self):
        with self.assertRaises(mod_m2.M2Error) as ctx:
            mod_m2.create_campaign(campaign_payload(process="3d-printing"), "admin")
        self.assertEqual(ctx.exception.error, "invalid_field")

    def test_pledge_below_min_batch_does_not_fund(self):
        campaign = self.open_campaign()
        result = mod_m2.create_pledge(campaign["id"], {"backer": "支持者A", "qty": 12}, "buyer")
        self.assertFalse(result["funded"])
        self.assertEqual(result["campaign"]["status"], "open")
        self.assertEqual(result["campaign"]["pledgedQty"], 12)
        self.assertEqual(len(mod_m2.store().list("production_orders")), 0)
        self.assertEqual(result["pledge"]["depositCents"], round(campaign["unitCents"] * 12 * 0.3))

    def test_pledge_reaching_min_batch_funds_and_creates_order(self):
        campaign = self.open_campaign()
        mod_m2.create_pledge(campaign["id"], {"backer": "支持者A", "qty": 12}, "buyer")
        result = mod_m2.create_pledge(campaign["id"], {"backer": "支持者B", "qty": 8}, "buyer")
        self.assertTrue(result["funded"])
        self.assertEqual(result["campaign"]["status"], "funded")
        order = mod_m2._order(result["campaign"]["productionOrderId"])
        self.assertEqual(order["status"], "created")
        self.assertEqual(order["qty"], 20)
        self.assertEqual(order["grossCents"], campaign["unitCents"] * 20)
        self.assertEqual(order["depositCents"], result["campaign"]["pledgedDepositCents"])

    def test_cancel_open_campaign_refunds_deposits(self):
        campaign = self.open_campaign()
        mod_m2.create_pledge(campaign["id"], {"backer": "支持者A", "qty": 3}, "buyer")
        cancelled = mod_m2.cancel_campaign(campaign["id"], {"reason": "未成团取消"}, "admin")
        self.assertEqual(cancelled["status"], "cancelled")
        pledges = mod_m2.store().list("pledges")
        self.assertEqual(pledges[0]["status"], "refunded")
        kinds = [row["type"] for row in mod_m2.store().list("ledger")]
        self.assertIn("refund_buyer", kinds)


class DispatchTests(M2Base):
    def test_dispatch_rejects_mismatched_workshop_with_five_checks(self):
        _, _, order = self.funded_order()
        with self.assertRaises(mod_m2.M2Error) as ctx:
            mod_m2.dispatch_order(order["id"], {"workshopId": "ws-jewel-02", "dimensionMm": 60}, "admin")
        self.assertEqual(ctx.exception.status, 422)
        self.assertEqual(ctx.exception.error, "capability_mismatch")
        checks = ctx.exception.extra["checks"]
        self.assertEqual(len(checks), 5)
        failed = [item["name"] for item in checks if not item["ok"]]
        self.assertEqual(failed, ["工艺匹配"])
        self.assertEqual(mod_m2._order(order["id"])["status"], "created")

    def test_preview_capability_does_not_change_status(self):
        _, _, order = self.funded_order()
        preview = mod_m2.preview_capability(order["id"], {"workshopId": "ws-jewel-01", "dimensionMm": 60})
        self.assertTrue(preview["passed"])
        preview_bad = mod_m2.preview_capability(order["id"], {"workshopId": "ws-jewel-02", "dimensionMm": 60})
        self.assertFalse(preview_bad["passed"])
        self.assertEqual(mod_m2._order(order["id"])["status"], "created")

    def test_dispatch_accept_moves_campaign_in_production(self):
        campaign, _, order = self.funded_order()
        dispatch = mod_m2.dispatch_order(order["id"], {"workshopId": "ws-jewel-01", "dimensionMm": 60}, "admin")["dispatch"]
        self.assertEqual(dispatch["status"], "offered")
        mod_m2.respond_dispatch(dispatch["id"], {"accept": True, "note": "可做"}, "workshop")
        updated = mod_m2._order(order["id"])
        self.assertEqual(updated["status"], "accepted")
        self.assertEqual(updated["workshopId"], "ws-jewel-01")
        self.assertEqual(mod_m2._campaign(campaign["id"])["status"], "in_production")

    def test_decline_returns_order_to_created(self):
        campaign, _, order = self.funded_order()
        dispatch = mod_m2.dispatch_order(order["id"], {"workshopId": "ws-jewel-01", "dimensionMm": 60}, "admin")["dispatch"]
        mod_m2.respond_dispatch(dispatch["id"], {"accept": False, "note": "工期不符"}, "workshop")
        self.assertEqual(mod_m2._order(order["id"])["status"], "created")
        self.assertEqual(mod_m2._campaign(campaign["id"])["status"], "funded")


class QualityAndSettlementTests(M2Base):
    def test_qc_failure_requires_note_and_triggers_rework(self):
        order = self.accepted_order()
        mod_m2.submit_qc(order["id"], "ops")
        with self.assertRaises(mod_m2.M2Error) as ctx:
            mod_m2.qc_result(order["id"], {"result": "fail"}, "admin")
        self.assertEqual(ctx.exception.error, "note_required")
        mod_m2.qc_result(order["id"], {"result": "fail", "note": "边缘有毛刺"}, "admin")
        order = mod_m2._order(order["id"])
        self.assertEqual(order["status"], "rework")
        self.assertEqual(order["quality"]["reworkCount"], 1)

    def test_settlement_balances_and_records_three_entries(self):
        order = self.shipped_order()
        before = len(mod_m2.store().list("ledger"))
        result = mod_m2.settle_order(order["id"], "finance")
        settled = result["order"]
        self.assertEqual(settled["status"], "settled")
        st = settled["settlement"]
        self.assertTrue(st["balanced"])
        self.assertEqual(st["platformFeeCents"], round(st["grossCents"] * 0.25))
        self.assertEqual(st["licenseRoyaltyCents"], round(st["grossCents"] * 0.10))
        self.assertEqual(
            st["platformFeeCents"] + st["licenseRoyaltyCents"] + st["workshopPayoutCents"],
            st["grossCents"],
        )
        self.assertEqual(len(result["ledger"]), 3)
        self.assertEqual(len(mod_m2.store().list("ledger")), before + 3)
        self.assertEqual(mod_m2._campaign(settled["campaignId"])["status"], "completed")
        with self.assertRaises(mod_m2.M2Error) as ctx:
            mod_m2.settle_order(order["id"], "finance")
        self.assertEqual(ctx.exception.error, "invalid_status")

    def test_dispute_refund_creates_balanced_ledger_rows(self):
        order = self.shipped_order()
        dispute = mod_m2.create_dispute({"orderId": order["id"], "type": "quality", "reason": "表面有明显划痕"}, "buyer")
        result = mod_m2.resolve_dispute(dispute["id"], {"resolution": "refund", "refundPct": 0.3, "note": "协商部分退款"}, "finance")
        gross = mod_m2._order(order["id"])["grossCents"]
        self.assertEqual(result["dispute"]["refundCents"], round(gross * 0.3))
        types = {row["type"]: row["amountCents"] for row in result["ledger"]}
        self.assertEqual(types["refund_buyer"], round(gross * 0.3))
        self.assertEqual(types["workshop_adjust"], -round(gross * 0.3))

    def test_rework_after_rework_limit_escalates(self):
        order = self.accepted_order()
        for _ in range(2):
            mod_m2.submit_qc(order["id"], "ops")
            mod_m2.qc_result(order["id"], {"result": "fail", "note": "仍有瑕疵"}, "admin")
            mod_m2.start_order(order["id"], "workshop")
        mod_m2.submit_qc(order["id"], "ops")
        mod_m2.qc_result(order["id"], {"result": "fail", "note": "第三次仍不合格"}, "admin")
        order = mod_m2._order(order["id"])
        self.assertEqual(order["status"], "escalated")
        self.assertEqual(order["quality"]["reworkCount"], 3)


class PermissionAndResetTests(M2Base):
    def test_role_permissions_are_enforced(self):
        campaign = self.open_campaign()
        with self.assertRaises(mod_m2.M2Error) as ctx:
            mod_m2.create_pledge(campaign["id"], {"backer": "越权者", "qty": 1}, "designer")
        self.assertEqual(ctx.exception.status, 403)
        order = self.shipped_order()
        with self.assertRaises(mod_m2.M2Error) as ctx:
            mod_m2.settle_order(order["id"], "designer")
        self.assertEqual(ctx.exception.status, 403)

    def test_reset_demo_clears_all_collections(self):
        self.shipped_order()
        mod_m2.reset_demo()
        for coll in ("campaigns", "pledges", "production_orders", "dispatches", "ledger", "disputes", "events"):
            self.assertEqual(mod_m2.store().list(coll), [], coll)


if __name__ == "__main__":
    unittest.main()
