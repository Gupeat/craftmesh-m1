from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import uuid
from typing import Any

PLATFORM_FEE_BPS = 2500


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


PATTERNS: list[dict[str, Any]] = [
    {
        "id": "moon-gate",
        "name": "月洞门",
        "subtitle": "合成原创",
        "source": "original",
        "sourceId": "",
        "licenseId": "ORIG-SYN-001",
        "useScope": ["commercial", "derivative"],
        "derivativeAllowed": True,
        "motif": "arc",
        "palette": ["#2a2118", "#d8b36a", "#f0d39a"],
    },
    {
        "id": "wave-lattice",
        "name": "海浪格",
        "subtitle": "合成授权",
        "source": "licensed",
        "sourceId": "SYN-LIC-001",
        "licenseId": "LIC-SYN-2026-001",
        "useScope": ["commercial"],
        "derivativeAllowed": True,
        "motif": "wave",
        "palette": ["#12232b", "#6fb6d8", "#b9e2f2"],
    },
    {
        "id": "cloud-scroll",
        "name": "云纹",
        "subtitle": "公版",
        "source": "public-domain",
        "sourceId": "PD-SYN-009",
        "licenseId": "PD-SYN-009",
        "useScope": ["commercial", "derivative"],
        "derivativeAllowed": True,
        "motif": "scroll",
        "palette": ["#2a1512", "#d97757", "#f2c3a8"],
    },
]

SOURCE_LABELS = {
    "original": "原创",
    "licensed": "授权",
    "public-domain": "公版",
}

PROCESS_LABELS = {
    "casting": "铸造",
    "inlay": "镶嵌",
    "engraving": "雕刻",
    "joinery": "榫卯",
    "carving": "木雕",
}

MATERIAL_LABELS = {"brass": "黄铜", "silver": "银", "wood": "木"}
FINISH_LABELS = {"polished": "抛光", "matte": "哑光", "oil": "木油", "wax": "木蜡"}
MODE_LABELS = {"copy": "复刻", "recombine": "重组", "original": "原创"}
USE_LABELS = {"commercial": "商业使用", "internal": "内部使用", "personal": "个人非商业"}

UNIT_CENTS = {"casting": 4200, "inlay": 6800, "engraving": 2800, "joinery": 5200, "carving": 4600}

STATUS_LABELS = {
    "draft": "草稿",
    "submitted": "待评审",
    "accepted": "已接单",
    "rework": "退回修改",
    "in_production": "生产中",
    "qc": "质检中",
    "shipped": "已发货",
    "settled": "已结算",
    "cancelled": "已取消",
}

ACTORS = {
    "designer": {"name": "林工", "title": "设计 / 工艺"},
    "reviewer": {"name": "周审", "title": "评审"},
    "ops": {"name": "陈厂", "title": "生产运营"},
    "qc": {"name": "质检组", "title": "质检"},
    "finance": {"name": "财务组", "title": "结算"},
    "admin": {"name": "管理员", "title": "平台管理"},
}

PARAM_DEFS = [
    {"key": "wallThickness", "label": "铸件壁厚", "unit": "mm", "default": 1.5, "step": 0.1, "type": "float"},
    {"key": "undercutAngle", "label": "脱模角", "unit": "°", "default": 3, "step": 0.5, "type": "float"},
    {"key": "inlayGap", "label": "镶嵌间隙", "unit": "mm", "default": 0.2, "step": 0.01, "type": "float"},
    {"key": "stoneHardness", "label": "宝石硬度", "unit": "", "default": 6, "step": 0.1, "type": "float"},
    {"key": "engraveWidth", "label": "刻线宽度", "unit": "mm", "default": 0.3, "step": 0.05, "type": "float"},
    {"key": "jointDepth", "label": "榫头深度", "unit": "mm", "default": 8, "step": 0.5, "type": "float"},
    {"key": "thickness", "label": "木料厚度", "unit": "mm", "default": 20, "step": 1, "type": "float"},
    {"key": "grainAngle", "label": "逆纹角度", "unit": "°", "default": 0, "step": 1, "type": "float"},
    {"key": "carveDepth", "label": "雕刻深度", "unit": "mm", "default": 1, "step": 0.5, "type": "float"},
    {"key": "moisture", "label": "木材含水率", "unit": "%", "default": 8, "step": 0.5, "type": "float"},
    {"key": "stoneDiameter", "label": "宝石直径", "unit": "mm", "default": 2, "step": 0.5, "type": "float"},
    {"key": "prongs", "label": "爪数", "unit": "", "default": 4, "step": 1, "type": "int"},
]

METAL_FINISHES = {"polished", "matte"}
WOOD_FINISHES = {"oil", "wax", "matte"}


def _f(p: dict, key: str) -> float:
    return float(p.get(key, 0))


RULES: list[dict[str, Any]] = [
    {
        "id": "CAST-WALL",
        "name": "铸件最小壁厚",
        "processes": ["casting"],
        "condition": "壁厚 >= 1.2 mm",
        "hard": True,
        "check": lambda p, m, f: _f(p, "wallThickness") >= 1.2,
        "detail": lambda p: f"{_f(p, 'wallThickness'):.2f} mm",
    },
    {
        "id": "CAST-UNDERCUT",
        "name": "铸造脱模角",
        "processes": ["casting"],
        "condition": "脱模角 >= 2°",
        "hard": False,
        "check": lambda p, m, f: _f(p, "undercutAngle") >= 2,
        "detail": lambda p: f"{_f(p, 'undercutAngle'):.1f}°",
    },
    {
        "id": "INLAY-GAP",
        "name": "镶嵌最小间隙",
        "processes": ["inlay"],
        "condition": "间隙 >= 0.15 mm",
        "hard": True,
        "check": lambda p, m, f: _f(p, "inlayGap") >= 0.15,
        "detail": lambda p: f"{_f(p, 'inlayGap'):.2f} mm",
    },
    {
        "id": "INLAY-HARDNESS",
        "name": "宝石硬度上限",
        "processes": ["inlay"],
        "condition": "硬度 <= 7.0",
        "hard": False,
        "check": lambda p, m, f: _f(p, "stoneHardness") <= 7.0,
        "detail": lambda p: f"{_f(p, 'stoneHardness'):.1f}",
    },
    {
        "id": "ENGRAVE-WIDTH",
        "name": "刻线最小宽度",
        "processes": ["engraving"],
        "condition": "线宽 >= 0.2 mm",
        "hard": False,
        "check": lambda p, m, f: _f(p, "engraveWidth") >= 0.2,
        "detail": lambda p: f"{_f(p, 'engraveWidth'):.2f} mm",
    },
    {
        "id": "JOINT-DEPTH",
        "name": "榫卯深度上限",
        "processes": ["joinery"],
        "condition": "榫深 <= 0.6 x 木料厚",
        "hard": False,
        "check": lambda p, m, f: _f(p, "jointDepth") <= _f(p, "thickness") * 0.6,
        "detail": lambda p: f"{_f(p, 'jointDepth'):.1f} / {_f(p, 'thickness') * 0.6:.1f} mm",
    },
    {
        "id": "CARVE-GRAIN",
        "name": "逆纹雕刻限制",
        "processes": ["carving"],
        "condition": "逆纹角 > 45° 时雕深 <= 3 mm",
        "hard": True,
        "check": lambda p, m, f: not (_f(p, "grainAngle") > 45 and _f(p, "carveDepth") > 3),
        "detail": lambda p: f"{_f(p, 'grainAngle'):.0f}° / {_f(p, 'carveDepth'):.1f} mm",
    },
    {
        "id": "WOOD-MOISTURE",
        "name": "木材含水率",
        "processes": ["joinery", "carving"],
        "condition": "含水率 <= 12%",
        "hard": False,
        "check": lambda p, m, f: _f(p, "moisture") <= 12,
        "detail": lambda p: f"{_f(p, 'moisture'):.1f}%",
    },
    {
        "id": "PRONG-COUNT",
        "name": "宝石爪数",
        "processes": ["casting", "inlay"],
        "condition": "石径 > 3 mm 时爪数 >= 4，否则 >= 3",
        "hard": False,
        "check": lambda p, m, f: int(_f(p, "prongs")) >= (4 if _f(p, "stoneDiameter") > 3 else 3),
        "detail": lambda p: f"{int(_f(p, 'prongs'))} 爪 / {_f(p, 'stoneDiameter'):.1f} mm",
    },
    {
        "id": "SURFACE-FINISH",
        "name": "表面处理匹配",
        "processes": ["casting", "inlay", "engraving", "joinery", "carving"],
        "condition": "金属抛光/哑光；木作木油/木蜡/哑光",
        "hard": False,
        "check": lambda p, m, f: (f in WOOD_FINISHES) if m == "wood" else (f in METAL_FINISHES),
        "detail": lambda p: "",
    },
]

HARD_RULE_IDS = {r["id"] for r in RULES if r["hard"]}

TRANSITIONS: dict[str, dict[str, Any]] = {
    "submit": {"label": "提交评审", "from": ["draft"], "to": "submitted", "roles": ["designer", "admin"]},
    "accept": {"label": "评审通过", "from": ["submitted"], "to": "accepted", "roles": ["reviewer", "admin"]},
    "request_rework": {"label": "退回修改", "from": ["submitted"], "to": "rework", "roles": ["reviewer", "admin"]},
    "resubmit": {"label": "重新提交", "from": ["rework"], "to": "submitted", "roles": ["designer", "admin"]},
    "start_production": {"label": "开始生产", "from": ["accepted"], "to": "in_production", "roles": ["ops", "admin"]},
    "send_to_qc": {"label": "送质检", "from": ["in_production"], "to": "qc", "roles": ["ops", "admin"]},
    "pass_qc": {"label": "质检通过", "from": ["qc"], "to": "shipped", "roles": ["qc", "admin"]},
    "reject_qc": {"label": "质检退回", "from": ["qc"], "to": "rework", "roles": ["qc", "admin"]},
    "settle": {"label": "结算", "from": ["shipped"], "to": "settled", "roles": ["finance", "admin"]},
    "cancel": {"label": "取消订单", "from": ["draft", "submitted", "accepted", "rework"], "to": "cancelled", "roles": ["admin"]},
}

NOTE_REQUIRED = {"request_rework", "reject_qc"}


def public_pattern(pattern: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(pattern)


def public_rule(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": rule["id"],
        "name": rule["name"],
        "processes": list(rule["processes"]),
        "condition": rule["condition"],
        "hard": bool(rule["hard"]),
    }


def public_transition(action: str, spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": action,
        "label": spec["label"],
        "from": list(spec["from"]),
        "to": spec["to"],
        "roles": list(spec["roles"]),
    }


def normalize_params(params: dict[str, Any] | None) -> dict[str, float]:
    src = params or {}
    out: dict[str, float] = {}
    for d in PARAM_DEFS:
        raw = src.get(d["key"], d["default"])
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = float(d["default"])
        if d["type"] == "int":
            value = int(round(value))
        out[d["key"]] = value
    return out


def validate_license(pattern: dict[str, Any], use: str = "commercial", derivative: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    source = pattern.get("source")
    if source not in SOURCE_LABELS:
        errors.append("授权来源缺失或不在允许范围内")
    scope = pattern.get("useScope") or []
    if use not in scope:
        errors.append(f"授权范围不含 {use}")
    if source == "licensed" and not pattern.get("sourceId"):
        errors.append("授权纹样缺少授权编号")
    if derivative and not pattern.get("derivativeAllowed"):
        errors.append("该纹样不允许二创")
    return {
        "ok": not errors,
        "errors": errors,
        "snapshot": {
            "patternId": pattern.get("id"),
            "patternName": pattern.get("name"),
            "source": source,
            "sourceId": pattern.get("sourceId", ""),
            "licenseId": pattern.get("licenseId", ""),
            "useScope": list(scope),
            "use": use,
            "derivative": bool(derivative),
            "derivativeAllowed": bool(pattern.get("derivativeAllowed")),
            "checkedAt": utcnow(),
        },
    }


def run_checks(process: str, material: str, finish: str, params: dict[str, Any] | None) -> dict[str, Any]:
    normalized = normalize_params(params)
    rows: list[dict[str, Any]] = []
    for rule in RULES:
        applies = process in rule["processes"]
        if not applies:
            rows.append({
                "id": rule["id"], "name": rule["name"], "condition": rule["condition"],
                "hard": bool(rule["hard"]), "status": "na", "detail": "本工艺不适用",
            })
            continue
        try:
            passed = bool(rule["check"](normalized, material, finish))
        except Exception:
            passed = False
        detail = ""
        try:
            detail = rule["detail"](normalized)
        except Exception:
            detail = ""
        rows.append({
            "id": rule["id"], "name": rule["name"], "condition": rule["condition"],
            "hard": bool(rule["hard"]), "status": "pass" if passed else "fail", "detail": detail,
        })
    failures = [r for r in rows if r["status"] == "fail"]
    hard_fail = any(r["hard"] for r in failures)
    soft_fail = any(not r["hard"] for r in failures)
    verdict = "blocked" if hard_fail else ("review" if soft_fail else "pass")
    return {
        "checks": rows,
        "verdict": verdict,
        "hardFail": hard_fail,
        "softFail": soft_fail,
        "failures": failures,
        "ok": not failures,
        "unmanufacturable": hard_fail,
    }


def quote(process: str, quantity: int) -> dict[str, int]:
    unit = UNIT_CENTS.get(process, 0)
    amount = unit * quantity
    fee = round(amount * PLATFORM_FEE_BPS / 10000)
    return {"unitCents": unit, "amountCents": amount, "platformFeeCents": fee, "netCents": amount - fee}


def _find_pattern(pattern_id: str) -> dict[str, Any] | None:
    for p in PATTERNS:
        if p["id"] == pattern_id:
            return p
    return None


HUMAN_RULE_CASES: list[dict[str, Any]] = [
    {"id": "H01", "title": "薄壁铸件", "ruleId": "CAST-WALL", "process": "casting", "material": "brass", "finish": "polished", "params": {"wallThickness": 0.5}, "human": "不可制造", "expected": "blocked"},
    {"id": "H02", "title": "脱模角不足", "ruleId": "CAST-UNDERCUT", "process": "casting", "material": "brass", "finish": "polished", "params": {"undercutAngle": 1}, "human": "需工艺复核", "expected": "review"},
    {"id": "H03", "title": "镶口间隙过小", "ruleId": "INLAY-GAP", "process": "inlay", "material": "brass", "finish": "polished", "params": {"inlayGap": 0.05}, "human": "不可制造", "expected": "blocked"},
    {"id": "H04", "title": "宝石硬度过高", "ruleId": "INLAY-HARDNESS", "process": "inlay", "material": "brass", "finish": "polished", "params": {"stoneHardness": 8}, "human": "需工艺复核", "expected": "review"},
    {"id": "H05", "title": "刻线过窄", "ruleId": "ENGRAVE-WIDTH", "process": "engraving", "material": "brass", "finish": "polished", "params": {"engraveWidth": 0.1}, "human": "需工艺复核", "expected": "review"},
    {"id": "H06", "title": "榫卯过深", "ruleId": "JOINT-DEPTH", "process": "joinery", "material": "wood", "finish": "oil", "params": {"jointDepth": 13, "thickness": 20}, "human": "需工艺复核", "expected": "review"},
    {"id": "H07", "title": "逆纹深雕", "ruleId": "CARVE-GRAIN", "process": "carving", "material": "wood", "finish": "oil", "params": {"grainAngle": 60, "carveDepth": 5}, "human": "不可制造", "expected": "blocked"},
    {"id": "H08", "title": "木材含水率偏高", "ruleId": "WOOD-MOISTURE", "process": "joinery", "material": "wood", "finish": "oil", "params": {"moisture": 15}, "human": "需工艺复核", "expected": "review"},
    {"id": "H09", "title": "大石爪数不足", "ruleId": "PRONG-COUNT", "process": "casting", "material": "brass", "finish": "polished", "params": {"stoneDiameter": 4, "prongs": 3}, "human": "需工艺复核", "expected": "review"},
    {"id": "H10", "title": "金属表面用木油", "ruleId": "SURFACE-FINISH", "process": "casting", "material": "brass", "finish": "oil", "params": {}, "human": "需工艺复核", "expected": "review"},
]


def human_rule_results() -> list[dict[str, Any]]:
    names = {rule["id"]: rule["name"] for rule in RULES}
    rows: list[dict[str, Any]] = []
    for case in HUMAN_RULE_CASES:
        result = run_checks(case["process"], case["material"], case["finish"], case["params"])
        failed = [row["id"] for row in result["failures"]]
        rows.append({
            "id": case["id"],
            "title": case["title"],
            "ruleId": case["ruleId"],
            "ruleName": names.get(case["ruleId"], case["ruleId"]),
            "human": case["human"],
            "expected": case["expected"],
            "actual": result["verdict"],
            "matched": result["verdict"] == case["expected"] and case["ruleId"] in failed,
        })
    return rows


def check_request(
    pattern_id: str,
    process: str,
    material: str,
    finish: str,
    quantity: int,
    params: dict[str, Any] | None,
    mode: str = "recombine",
    use: str = "commercial",
) -> dict[str, Any]:
    errors: list[str] = []
    pattern = _find_pattern(pattern_id)
    if pattern is None:
        return {"ok": False, "error": "pattern_not_found", "errors": ["纹样不存在"]}
    if process not in PROCESS_LABELS:
        errors.append("工艺不在允许范围内")
    if material not in MATERIAL_LABELS:
        errors.append("材料不在允许范围内")
    if finish not in FINISH_LABELS:
        errors.append("表面处理不在允许范围内")
    if mode not in MODE_LABELS:
        errors.append("共创模式不在允许范围内")
    if use not in USE_LABELS:
        errors.append("授权用途不在允许范围内")
    try:
        qty = int(quantity)
    except (TypeError, ValueError):
        qty = 0
    if qty < 1 or qty > 10000:
        errors.append("数量需在 1–10000 之间")
    derivative = mode in {"recombine", "original"}
    license_result = validate_license(pattern, use, derivative)
    checks = run_checks(process, material, finish, params)
    normalized = normalize_params(params)
    if checks["hardFail"]:
        hard_ids = [r["id"] for r in checks["failures"] if r["hard"]]
        errors.append("硬约束未通过：" + ", ".join(hard_ids))
    ok = license_result["ok"] and not checks["hardFail"] and not errors
    return {
        "ok": ok,
        "pattern": public_pattern(pattern),
        "process": process,
        "material": material,
        "finish": finish,
        "mode": mode,
        "use": use,
        "useLabel": USE_LABELS.get(use, use),
        "quantity": qty,
        "params": normalized,
        "license": license_result,
        "checks": checks,
        "quote": quote(process, qty),
        "errors": errors + license_result["errors"],
    }


def create_order(
    pattern_id: str,
    process: str,
    material: str,
    finish: str,
    quantity: int,
    params: dict[str, Any] | None,
    mode: str = "recombine",
    actor_role: str = "designer",
    use: str = "commercial",
) -> dict[str, Any]:
    if actor_role not in {"designer", "admin"}:
        return {"ok": False, "error": "permission_denied", "errors": ["当前角色不能创建订单"]}
    request = check_request(pattern_id, process, material, finish, quantity, params, mode, use)
    if not request["ok"]:
        return {"ok": False, "error": "validation_failed", "errors": request["errors"], "checks": request.get("checks")}
    now = utcnow()
    order = {
        "id": "ORD-" + uuid.uuid4().hex[:8].upper(),
        "pattern": request["pattern"],
        "process": process,
        "processLabel": PROCESS_LABELS[process],
        "material": material,
        "materialLabel": MATERIAL_LABELS[material],
        "finish": finish,
        "finishLabel": FINISH_LABELS[finish],
        "mode": mode,
        "modeLabel": MODE_LABELS[mode],
        "use": request["use"],
        "useLabel": request["useLabel"],
        "quantity": request["quantity"],
        "params": request["params"],
        "license": request["license"]["snapshot"],
        "checks": request["checks"]["checks"],
        "verdict": request["checks"]["verdict"],
        "reviewRequired": request["checks"]["verdict"] == "review",
        "quote": request["quote"],
        "status": "draft",
        "version": 1,
        "createdAt": now,
        "updatedAt": now,
        "createdBy": ACTORS.get(actor_role, ACTORS["designer"])["name"],
    }
    return {"ok": True, "order": order}


def allowed_actions(order: dict[str, Any], role: str) -> list[str]:
    return [
        action for action, spec in TRANSITIONS.items()
        if order["status"] in spec["from"] and role in spec["roles"]
    ]


def apply_transition(order: dict[str, Any], action: str, role: str, note: str = "") -> dict[str, Any]:
    spec = TRANSITIONS.get(action)
    if spec is None:
        return {"ok": False, "error": "unknown_action", "errors": ["未知状态动作"]}
    if role not in spec["roles"]:
        return {"ok": False, "error": "permission_denied", "errors": ["当前角色无此操作权限"]}
    if order["status"] not in spec["from"]:
        return {"ok": False, "error": "invalid_state", "errors": ["当前状态不允许该动作"]}
    if action in NOTE_REQUIRED and not str(note).strip():
        return {"ok": False, "error": "note_required", "errors": ["该动作需要填写原因"]}
    now = utcnow()
    updated = deepcopy(order)
    updated["status"] = spec["to"]
    updated["version"] = int(updated.get("version", 1)) + 1
    updated["updatedAt"] = now
    event = {
        "at": now,
        "action": action,
        "label": spec["label"],
        "from": order["status"],
        "to": spec["to"],
        "role": role,
        "actor": ACTORS.get(role, {"name": role})["name"],
        "note": str(note).strip()[:500],
    }
    return {"ok": True, "order": updated, "event": event}
