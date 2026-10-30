from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core


BASE_PARAMS = {
    "wallThickness": 1.5, "undercutAngle": 3, "inlayGap": 0.2, "stoneHardness": 6,
    "engraveWidth": 0.3, "jointDepth": 8, "thickness": 20, "grainAngle": 0,
    "carveDepth": 1, "moisture": 8, "stoneDiameter": 2, "prongs": 4,
}


class CoreTests(unittest.TestCase):
    def test_patterns_are_synthetic_and_have_license_fields(self):
        self.assertEqual(len(core.PATTERNS), 3)
        for p in core.PATTERNS:
            self.assertIn(p["source"], {"original", "licensed", "public-domain"})
            self.assertTrue(p["useScope"])
            self.assertIn("licenseId", p)

    def test_ten_rules_three_hard(self):
        self.assertEqual(len(core.RULES), 10)
        self.assertEqual(len(core.HARD_RULE_IDS), 3)
        for rid in ("CAST-WALL", "INLAY-GAP", "CARVE-GRAIN"):
            self.assertIn(rid, core.HARD_RULE_IDS)

    def test_valid_casting_passes(self):
        result = core.run_checks("casting", "brass", "polished", BASE_PARAMS)
        self.assertEqual(result["verdict"], "pass")
        self.assertTrue(result["ok"])
        self.assertFalse(result["unmanufacturable"])

    def test_thin_wall_is_blocked(self):
        params = dict(BASE_PARAMS, wallThickness=0.5)
        result = core.run_checks("casting", "brass", "polished", params)
        self.assertEqual(result["verdict"], "blocked")
        self.assertTrue(result["unmanufacturable"])
        self.assertIn("CAST-WALL", [r["id"] for r in result["failures"]])

    def test_inlay_gap_is_blocked(self):
        params = dict(BASE_PARAMS, inlayGap=0.05)
        result = core.run_checks("inlay", "brass", "polished", params)
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("INLAY-GAP", [r["id"] for r in result["failures"]])

    def test_reverse_grain_carving_is_blocked(self):
        params = dict(BASE_PARAMS, grainAngle=90, carveDepth=6)
        result = core.run_checks("carving", "wood", "oil", params)
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("CARVE-GRAIN", [r["id"] for r in result["failures"]])

    def test_soft_failure_returns_review(self):
        params = dict(BASE_PARAMS, undercutAngle=1)
        result = core.run_checks("casting", "brass", "polished", params)
        self.assertEqual(result["verdict"], "review")
        self.assertFalse(result["unmanufacturable"])
        self.assertTrue(result["softFail"])

    def test_original_license_passes(self):
        result = core.validate_license(core.PATTERNS[0], "commercial", True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["snapshot"]["source"], "original")

    def test_licensed_requires_source_id(self):
        pattern = dict(core.PATTERNS[1], sourceId="")
        result = core.validate_license(pattern, "commercial", False)
        self.assertFalse(result["ok"])
        self.assertTrue(any("授权编号" in e for e in result["errors"]))

    def test_non_commercial_scope_is_rejected(self):
        pattern = dict(core.PATTERNS[0], useScope=["internal"])
        result = core.validate_license(pattern, "commercial", False)
        self.assertFalse(result["ok"])

    def test_derivative_permission_is_rejected(self):
        pattern = dict(core.PATTERNS[0], derivativeAllowed=False)
        result = core.validate_license(pattern, "commercial", True)
        self.assertFalse(result["ok"])
        self.assertTrue(any("二创" in e for e in result["errors"]))

    def test_create_order_snapshots_license_and_quote(self):
        result = core.create_order("moon-gate", "casting", "brass", "polished", 10, BASE_PARAMS, "recombine", "designer")
        self.assertTrue(result["ok"])
        order = result["order"]
        self.assertEqual(order["status"], "draft")
        self.assertEqual(order["pattern"]["id"], "moon-gate")
        self.assertEqual(order["license"]["source"], "original")
        self.assertEqual(order["quote"]["amountCents"], 42000)
        self.assertEqual(order["quote"]["platformFeeCents"], 10500)
        self.assertEqual(order["quote"]["netCents"], 31500)

    def test_create_order_rejects_hard_constraint(self):
        result = core.create_order(
            "moon-gate", "casting", "brass", "polished", 10,
            dict(BASE_PARAMS, wallThickness=0.5), "recombine", "designer",
        )
        self.assertFalse(result["ok"])
        self.assertIn("CAST-WALL", " ".join(result["errors"]))

    def test_transition_flow(self):
        created = core.create_order("moon-gate", "casting", "brass", "polished", 1, BASE_PARAMS, "copy", "designer")["order"]
        steps = [("submit", "designer"), ("accept", "reviewer"), ("start_production", "ops"),
                 ("send_to_qc", "ops"), ("pass_qc", "qc"), ("settle", "finance")]
        order = created
        for action, role in steps:
            result = core.apply_transition(order, action, role)
            self.assertTrue(result["ok"], result)
            order = result["order"]
        self.assertEqual(order["status"], "settled")
        self.assertEqual(order["version"], 7)

    def test_transition_permission_denied(self):
        created = core.create_order("moon-gate", "casting", "brass", "polished", 1, BASE_PARAMS, "copy", "designer")["order"]
        result = core.apply_transition(created, "submit", "ops")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "permission_denied")

    def test_invalid_transition_from_draft(self):
        created = core.create_order("moon-gate", "casting", "brass", "polished", 1, BASE_PARAMS, "copy", "designer")["order"]
        result = core.apply_transition(created, "accept", "reviewer")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_state")

    def test_rework_requires_note(self):
        created = core.create_order("moon-gate", "casting", "brass", "polished", 1, BASE_PARAMS, "copy", "designer")["order"]
        submitted = core.apply_transition(created, "submit", "designer")["order"]
        result = core.apply_transition(submitted, "request_rework", "reviewer", "")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "note_required")
        result2 = core.apply_transition(submitted, "request_rework", "reviewer", "纹理方向需调整")
        self.assertTrue(result2["ok"])

    def test_allowed_actions_follow_status_and_role(self):
        created = core.create_order("moon-gate", "casting", "brass", "polished", 1, BASE_PARAMS, "copy", "designer")["order"]
        self.assertIn("submit", core.allowed_actions(created, "designer"))
        self.assertNotIn("submit", core.allowed_actions(created, "reviewer"))
        self.assertNotIn("accept", core.allowed_actions(created, "designer"))

    def test_param_normalization_uses_defaults(self):
        normalized = core.normalize_params({"wallThickness": "2.0", "prongs": "5", "unknown": 1})
        self.assertEqual(normalized["wallThickness"], 2.0)
        self.assertEqual(normalized["prongs"], 5)
        self.assertNotIn("unknown", normalized)


if __name__ == "__main__":
    unittest.main(verbosity=2)
