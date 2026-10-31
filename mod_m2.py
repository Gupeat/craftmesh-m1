"""M2 · C2M 预售与制造协同（可运行纵切）。

一条真实可点通的链路（每一步都由 API 与 SQLite 完成，不是静态展示）：

  创建预售活动 → 开放预售 → 支持者付定金下单 → 达到起订量自动成团
  → 生成工艺单（授权 / 工艺参数 / 报价快照）→ 派单给工坊（能力匹配校验）
  → 工坊接单 → 开工 → 提交质检 → 通过放行 / 不通过返工（需备注）
  → 发货 → 结算分账（平台 / 授权方 / 工坊）→ 买家争议与退款

规则数字在 config/m2_rules.json，工坊能力在 config/workshops.json，
两者都是纯数据文件，改完刷新页面即生效（按 mtime 热加载）。
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core import (
    MATERIAL_LABELS, PATTERNS, PROCESS_LABELS, FINISH_LABELS, SOURCE_LABELS, UNIT_CENTS,
    normalize_params, quote, utcnow, validate_license,
)
from jsonstore import JsonStore, new_id

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RULES_PATH = ROOT / "config" / "m2_rules.json"
WORKSHOPS_PATH = ROOT / "config" / "workshops.json"

ACTORS = {
    "designer": "设计师",
    "ops": "生产运营",
    "workshop": "工坊",
    "finance": "财务",
    "buyer": "买家 / 支持者",
    "admin": "管理员",
}

STATUS_LABELS = {
    "draft": "草稿",
    "open": "预售中",
    "funded": "已成团",
    "in_production": "生产中",
    "completed": "已完成",
    "cancelled": "已取消",
}

ORDER_LABELS = {
    "created": "待派单",
    "dispatched": "已派单",
    "accepted": "工坊已接单",
    "in_progress": "生产中",
    "qc_pending": "待质检",
    "qc_passed": "质检通过",
    "rework": "返工中",
    "shipped": "已发货",
    "settled": "已结算",
    "escalated": "返工超限待处理",
    "cancelled": "已取消",
}

DISPATCH_LABELS = {"offered": "待工坊确认", "accepted": "已接单", "declined": "已拒单"}

PERMISSIONS = {
    "campaign.create": ["designer", "admin"],
    "campaign.open": ["designer", "ops", "admin"],
    "campaign.cancel": ["designer", "ops", "admin"],
    "pledge.create": ["buyer", "admin"],
    "order.dispatch": ["designer", "ops", "admin"],
    "dispatch.respond": ["workshop", "admin"],
    "order.start": ["workshop", "ops", "admin"],
    "order.qc": ["ops", "admin"],
    "order.ship": ["ops", "admin"],
    "order.settle": ["finance", "admin"],
    "dispute.create": ["buyer", "admin"],
    "dispute.resolve": ["finance", "ops", "admin"],
}

CAMPAIGN_ROUTE = re.compile(r"^/api/m2/campaigns/([^/]+)$")
CAMPAIGN_ACTION = re.compile(r"^/api/m2/campaigns/([^/]+)/(open|pledge|cancel)$")
ORDER_ROUTE = re.compile(r"^/api/m2/production-orders/([^/]+)$")
ORDER_ACTION = re.compile(r"^/api/m2/production-orders/([^/]+)/(dispatch|start|submit-qc|qc|ship|settle)$")
ORDER_CAPABILITY = re.compile(r"^/api/m2/production-orders/([^/]+)/capability$")
DISPATCH_ACTION = re.compile(r"^/api/m2/dispatches/([^/]+)/respond$")
DISPUTE_ACTION = re.compile(r"^/api/m2/disputes/([^/]+)/resolve$")


# --------------------------------------------------------------------------- #
# 基础设施：配置热加载、存储、响应、错误
# --------------------------------------------------------------------------- #
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _load_json(path: Path) -> Any:
    stamp = path.stat().st_mtime
    with _cache_lock:
        hit = _cache.get(str(path))
        if hit and hit[0] == stamp:
            return hit[1]
    data = json.loads(path.read_text(encoding="utf-8"))
    with _cache_lock:
        _cache[str(path)] = (stamp, data)
    return data


def rules() -> dict[str, Any]:
    return _load_json(RULES_PATH)


def workshops() -> list[dict[str, Any]]:
    data = _load_json(WORKSHOPS_PATH)
    return list(data.get("workshops") or [])


def workshop_map() -> dict[str, dict[str, Any]]:
    return {w["id"]: w for w in workshops()}


_store: JsonStore | None = None
_store_lock = threading.Lock()


def store() -> JsonStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = JsonStore(DATA_DIR / "m2.db", "m2")
        return _store


class M2Error(Exception):
    def __init__(self, status: int, error: str, message: str, extra: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.error = error
        self.message = message
        self.extra = extra or {}


def _send(handler, status: int, payload: dict[str, Any]) -> None:
    handler._send_json(status, payload)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log(scope: str, ref: str, action: str, label: str, from_status: str, to_status: str, role: str, note: str = "") -> None:
    st = store()
    event_id = new_id("evt")
    st.put("events", event_id, {
        "id": event_id, "at": _now(), "scope": scope, "refId": ref,
        "action": action, "label": label, "from": from_status, "to": to_status,
        "role": role, "actor": ACTORS.get(role, role), "note": note,
    })


def _require_role(role: str, capability: str) -> None:
    allowed = PERMISSIONS.get(capability, [])
    if role not in allowed:
        raise M2Error(403, "permission_denied", f"角色 {ACTORS.get(role, role)} 无权执行该操作", {
            "capability": capability,
            "allowedRoles": [{"role": r, "label": ACTORS.get(r, r)} for r in allowed],
        })


def _int(value: Any, field: str, minimum: int = 1, maximum: int = 100000) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise M2Error(422, "invalid_field", f"{field} 必须是整数") from None
    if number < minimum or number > maximum:
        raise M2Error(422, "invalid_field", f"{field} 需在 {minimum}–{maximum} 之间")
    return number


def _pattern(pattern_id: str) -> dict[str, Any]:
    for pattern in PATTERNS:
        if pattern["id"] == pattern_id:
            return pattern
    raise M2Error(404, "pattern_not_found", f"纹样 {pattern_id or '(空)'} 不存在")


def _campaign(campaign_id: str) -> dict[str, Any]:
    campaign = store().get("campaigns", campaign_id)
    if campaign is None:
        raise M2Error(404, "campaign_not_found", f"预售活动 {campaign_id} 不存在")
    return campaign


def _order(order_id: str) -> dict[str, Any]:
    order = store().get("production_orders", order_id)
    if order is None:
        raise M2Error(404, "order_not_found", f"工艺单 {order_id} 不存在")
    return order


def _dispatch(dispatch_id: str) -> dict[str, Any]:
    row = store().get("dispatches", dispatch_id)
    if row is None:
        raise M2Error(404, "dispatch_not_found", f"派单 {dispatch_id} 不存在")
    return row


def _dispute(dispute_id: str) -> dict[str, Any]:
    row = store().get("disputes", dispute_id)
    if row is None:
        raise M2Error(404, "dispute_not_found", f"争议 {dispute_id} 不存在")
    return row


def _ledger_entry(ref: str, ref_type: str, kind: str, party: str, amount: int, note: str) -> dict[str, Any]:
    entry = {
        "id": new_id("led"),
        "at": _now(),
        "ref": ref,
        "refType": ref_type,
        "type": kind,
        "party": party,
        "amountCents": int(amount),
        "note": note,
    }
    store().put("ledger", entry["id"], entry)
    return entry


# --------------------------------------------------------------------------- #
# 业务动作
# --------------------------------------------------------------------------- #
def create_campaign(payload: dict[str, Any], role: str) -> dict[str, Any]:
    _require_role(role, "campaign.create")
    pattern = _pattern(str(payload.get("patternId") or payload.get("pattern_id") or ""))
    process = str(payload.get("process") or "")
    material = str(payload.get("material") or "")
    finish = str(payload.get("finish") or "")
    if process not in PROCESS_LABELS:
        raise M2Error(422, "invalid_field", f"工艺 {process or '(空)'} 不在支持范围")
    if material not in MATERIAL_LABELS:
        raise M2Error(422, "invalid_field", f"材料 {material or '(空)'} 不在支持范围")
    if finish not in FINISH_LABELS:
        raise M2Error(422, "invalid_field", f"表面处理 {finish or '(空)'} 不在支持范围")
    license_row = validate_license(pattern, str(payload.get("use") or "commercial"), bool(payload.get("derivative")))
    if not license_row["ok"]:
        raise M2Error(422, "license_denied", "授权校验未通过，不能开预售", {"errors": license_row["errors"]})
    quantity_per_unit = _int(payload.get("quantityPerUnit", 1), "每份件数", 1, 200)
    cfg = rules()
    min_batch = int(cfg["minBatch"].get(process, 10))
    quote_row = quote(process, quantity_per_unit)
    deposit_cents = round(quote_row["unitCents"] * quantity_per_unit * float(cfg["depositPct"]))
    deadline_days = _int(payload.get("deadlineDays", 14), "预售天数", 1, 90)
    campaign = {
        "id": new_id("cmp"),
        "status": "draft",
        "createdAt": _now(),
        "updatedAt": _now(),
        "pattern": {
            "id": pattern["id"], "name": pattern["name"], "source": pattern.get("source"),
            "sourceId": pattern.get("sourceId", ""), "licenseId": pattern.get("licenseId", ""),
            "useScope": pattern.get("useScope", []), "derivativeAllowed": bool(pattern.get("derivativeAllowed")),
        },
        "licenseSnapshot": license_row["snapshot"],
        "process": process, "material": material, "finish": finish,
        "params": normalize_params(payload.get("params") or {}),
        "quantityPerUnit": quantity_per_unit,
        "minBatch": min_batch,
        "unitCents": quote_row["unitCents"],
        "depositCentsPerUnit": deposit_cents,
        "depositPct": float(cfg["depositPct"]),
        "pledgedQty": 0,
        "pledgedDepositCents": 0,
        "deadlineAt": (datetime.now(timezone.utc) + timedelta(days=deadline_days)).isoformat(timespec="seconds"),
        "productionOrderId": "",
        "title": str(payload.get("title") or f"{pattern['name']} · {PROCESS_LABELS[process]}预售"),
        "notes": str(payload.get("notes") or ""),
    }
    store().put("campaigns", campaign["id"], campaign)
    _log("campaign", campaign["id"], "created", "创建预售活动", "", "draft", role)
    return campaign


def open_campaign(campaign_id: str, role: str) -> dict[str, Any]:
    _require_role(role, "campaign.open")
    campaign = _campaign(campaign_id)
    if campaign["status"] != "draft":
        raise M2Error(409, "invalid_status", f"只有草稿可开放预售，当前 {STATUS_LABELS.get(campaign['status'])}")
    campaign["status"] = "open"
    campaign["updatedAt"] = _now()
    campaign["openedAt"] = _now()
    store().put("campaigns", campaign_id, campaign)
    _log("campaign", campaign_id, "opened", "开放预售", "draft", "open", role)
    return campaign


def create_pledge(campaign_id: str, payload: dict[str, Any], role: str) -> dict[str, Any]:
    _require_role(role, "pledge.create")
    campaign = _campaign(campaign_id)
    if campaign["status"] != "open":
        raise M2Error(409, "invalid_status", f"预售活动当前不可下单：{STATUS_LABELS.get(campaign['status'])}")
    deadline = datetime.fromisoformat(campaign["deadlineAt"])
    if datetime.now(timezone.utc) > deadline:
        raise M2Error(409, "campaign_expired", "预售已过截止时间")
    qty = _int(payload.get("qty", 1), "订购份数", 1, 500)
    backer = str(payload.get("backer") or "").strip()[:40]
    if not backer:
        raise M2Error(422, "invalid_field", "支持者名称不能为空")
    deposit = campaign["unitCents"] * qty * campaign["quantityPerUnit"]
    deposit = round(deposit * campaign["depositPct"])
    pledge = {
        "id": new_id("plg"),
        "campaignId": campaign_id,
        "backer": backer,
        "qty": qty,
        "unitCents": campaign["unitCents"],
        "depositCents": deposit,
        "status": "paid",
        "createdAt": _now(),
    }
    store().put("pledges", pledge["id"], pledge)
    _ledger_entry(pledge["id"], "pledge", "deposit", "buyer", deposit, f"{backer} 预售定金 · {qty} 份")
    campaign["pledgedQty"] += qty
    campaign["pledgedDepositCents"] += deposit
    campaign["updatedAt"] = _now()
    funded = False
    if campaign["pledgedQty"] >= campaign["minBatch"] and campaign["status"] == "open":
        campaign["status"] = "funded"
        campaign["fundedAt"] = _now()
        order = _create_production_order(campaign, role)
        campaign["productionOrderId"] = order["id"]
        funded = True
    store().put("campaigns", campaign_id, campaign)
    _log("campaign", campaign_id, "pledged", f"{backer} 定金下单 {qty} 份", campaign["status"], campaign["status"], role,
         f"累计 {campaign['pledgedQty']}/{campaign['minBatch']}" + ("；达成起订量，自动成团" if funded else ""))
    return {"campaign": campaign, "pledge": pledge, "funded": funded}


def _create_production_order(campaign: dict[str, Any], role: str) -> dict[str, Any]:
    qty = campaign["pledgedQty"]
    gross = campaign["unitCents"] * qty * campaign["quantityPerUnit"]
    order = {
        "id": new_id("po"),
        "campaignId": campaign["id"],
        "patternId": campaign["pattern"]["id"],
        "patternName": campaign["pattern"]["name"],
        "licenseSnapshot": campaign["licenseSnapshot"],
        "process": campaign["process"],
        "material": campaign["material"],
        "finish": campaign["finish"],
        "params": campaign["params"],
        "qty": qty,
        "quantityPerUnit": campaign["quantityPerUnit"],
        "unitCents": campaign["unitCents"],
        "grossCents": gross,
        "depositCents": campaign["pledgedDepositCents"],
        "status": "created",
        "workshopId": "",
        "dispatchId": "",
        "createdAt": _now(),
        "updatedAt": _now(),
        "quality": {"attempts": 0, "reworkCount": 0, "lastResult": "", "lastNote": "", "history": []},
        "shipment": {},
        "settlement": {},
        "history": [{"action": "created", "label": "成团生成工艺单", "at": _now(), "role": role, "from": "", "to": "created", "note": f"{qty} 份"}],
    }
    store().put("production_orders", order["id"], order)
    _log("order", order["id"], "created", "成团生成工艺单", "", "created", role, f"gross={gross} 分")
    return order


def _capability_checks(order: dict[str, Any], workshop: dict[str, Any], dimension_mm: int) -> list[dict[str, Any]]:
    cfg = rules()["dispatch"]
    open_states = {"dispatched", "accepted", "in_progress", "qc_pending", "rework"}
    live = [o for o in store().list("production_orders", 500) if o.get("workshopId") == workshop["id"] and o["status"] in open_states]
    checks = [
        {"name": "工艺匹配", "ok": order["process"] in workshop.get("processes", []),
         "detail": f"工坊承接 {'/'.join(PROCESS_LABELS.get(p, p) for p in workshop.get('processes', []))}；本单 {PROCESS_LABELS.get(order['process'], order['process'])}"},
        {"name": "材料匹配", "ok": order["material"] in workshop.get("materials", []),
         "detail": f"工坊材料 {'/'.join(MATERIAL_LABELS.get(m, m) for m in workshop.get('materials', []))}；本单 {MATERIAL_LABELS.get(order['material'], order['material'])}"},
        {"name": "尺寸上限", "ok": dimension_mm <= int(workshop.get("maxDimensionMm", 0)),
         "detail": f"本单最大尺寸 {dimension_mm}mm ≤ 工坊上限 {workshop.get('maxDimensionMm')}mm"},
        {"name": "起订量", "ok": order["qty"] >= int(workshop.get("minOrderQty", 1)),
         "detail": f"本单 {order['qty']} 份 ≥ 工坊起订 {workshop.get('minOrderQty')} 份"},
        {"name": "在制产能", "ok": len(live) < int(cfg.get("maxConcurrentOrdersPerWorkshop", 3)),
         "detail": f"工坊在制 {len(live)} 单 / 上限 {cfg.get('maxConcurrentOrdersPerWorkshop', 3)} 单"},
    ]
    return checks


def preview_capability(order_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """派单前的能力预检：与 dispatch_order 共用 _capability_checks，不写任何状态。"""
    order = _order(order_id)
    workshop_id = str(payload.get("workshopId") or payload.get("workshop_id") or "")
    workshop = workshop_map().get(workshop_id)
    if workshop is None:
        raise M2Error(404, "workshop_not_found", f"工坊 {workshop_id or '(空)'} 不存在")
    dimension_mm = _int(payload.get("dimensionMm", rules()["dispatch"].get("defaultDimensionMm", 60)), "最大尺寸", 1, 5000)
    checks = _capability_checks(order, workshop, dimension_mm)
    return {
        "orderId": order["id"], "workshopId": workshop_id, "workshopName": workshop["name"],
        "dimensionMm": dimension_mm, "checks": checks, "passed": all(c["ok"] for c in checks),
    }


def dispatch_order(order_id: str, payload: dict[str, Any], role: str) -> dict[str, Any]:
    _require_role(role, "order.dispatch")
    order = _order(order_id)
    if order["status"] != "created":
        raise M2Error(409, "invalid_status", f"只有待派单的工艺单可派单，当前 {ORDER_LABELS.get(order['status'])}")
    campaign = _campaign(order["campaignId"])
    if campaign["status"] not in {"funded", "in_production"}:
        raise M2Error(409, "campaign_not_funded", "预售未成团，不能派单")
    workshop_id = str(payload.get("workshopId") or payload.get("workshop_id") or "")
    workshop = workshop_map().get(workshop_id)
    if workshop is None:
        raise M2Error(404, "workshop_not_found", f"工坊 {workshop_id or '(空)'} 不存在")
    dimension_mm = _int(payload.get("dimensionMm", rules()["dispatch"].get("defaultDimensionMm", 60)), "最大尺寸", 1, 5000)
    checks = _capability_checks(order, workshop, dimension_mm)
    failed = [c for c in checks if not c["ok"]]
    if failed:
        raise M2Error(422, "capability_mismatch", "工坊能力不匹配，派单被拒：" + "；".join(c["name"] for c in failed), {
            "checks": checks, "workshopId": workshop_id, "workshopName": workshop["name"],
        })
    dispatch = {
        "id": new_id("dsp"),
        "productionOrderId": order["id"],
        "workshopId": workshop_id,
        "workshopName": workshop["name"],
        "status": "offered",
        "dimensionMm": dimension_mm,
        "capability": {"checks": checks, "passed": True, "checkedAt": _now()},
        "offeredAt": _now(),
        "respondedAt": "",
        "note": str(payload.get("note") or ""),
    }
    store().put("dispatches", dispatch["id"], dispatch)
    order["status"] = "dispatched"
    order["dispatchId"] = dispatch["id"]
    order["updatedAt"] = _now()
    order["history"].append({"action": "dispatched", "label": "派单", "at": _now(), "role": role, "from": "created", "to": "dispatched", "note": workshop["name"]})
    store().put("production_orders", order["id"], order)
    _log("order", order["id"], "dispatched", f"派单给 {workshop['name']}", "created", "dispatched", role)
    return {"order": order, "dispatch": dispatch}


def respond_dispatch(dispatch_id: str, payload: dict[str, Any], role: str) -> dict[str, Any]:
    _require_role(role, "dispatch.respond")
    dispatch = _dispatch(dispatch_id)
    if dispatch["status"] != "offered":
        raise M2Error(409, "invalid_status", "该派单已处理")
    order = _order(dispatch["productionOrderId"])
    accept = bool(payload.get("accept"))
    dispatch["status"] = "accepted" if accept else "declined"
    dispatch["respondedAt"] = _now()
    dispatch["note"] = str(payload.get("note") or "")
    if accept:
        order["status"] = "accepted"
        order["workshopId"] = dispatch["workshopId"]
        campaign = _campaign(order["campaignId"])
        campaign["status"] = "in_production"
        campaign["updatedAt"] = _now()
        store().put("campaigns", campaign["id"], campaign)
    else:
        order["status"] = "created"
        order["dispatchId"] = ""
    order["updatedAt"] = _now()
    order["history"].append({
        "action": "dispatch_" + ("accepted" if accept else "declined"),
        "label": "工坊接单" if accept else "工坊拒单",
        "at": _now(), "role": role,
        "from": "dispatched", "to": order["status"], "note": dispatch["note"],
    })
    store().put("dispatches", dispatch_id, dispatch)
    store().put("production_orders", order["id"], order)
    _log("dispatch", dispatch_id, dispatch["status"], "工坊接单" if accept else "工坊拒单", "offered", dispatch["status"], role)
    return {"order": order, "dispatch": dispatch}


def start_order(order_id: str, role: str) -> dict[str, Any]:
    _require_role(role, "order.start")
    order = _order(order_id)
    if order["status"] not in {"accepted", "rework"}:
        raise M2Error(409, "invalid_status", f"当前状态 {ORDER_LABELS.get(order['status'])} 不能开工")
    previous = order["status"]
    order["status"] = "in_progress"
    order["updatedAt"] = _now()
    order["history"].append({"action": "started", "label": "开工", "at": _now(), "role": role, "from": previous, "to": "in_progress", "note": ""})
    store().put("production_orders", order_id, order)
    _log("order", order_id, "started", "开工", previous, "in_progress", role)
    return order


def submit_qc(order_id: str, role: str) -> dict[str, Any]:
    _require_role(role, "order.qc")
    order = _order(order_id)
    if order["status"] != "in_progress":
        raise M2Error(409, "invalid_status", f"当前状态 {ORDER_LABELS.get(order['status'])} 不能提交质检")
    order["status"] = "qc_pending"
    order["updatedAt"] = _now()
    order["history"].append({"action": "submitted_qc", "label": "提交质检", "at": _now(), "role": role, "from": "in_progress", "to": "qc_pending", "note": ""})
    store().put("production_orders", order_id, order)
    _log("order", order_id, "qc_submitted", "提交质检", "in_progress", "qc_pending", role)
    return order


def qc_result(order_id: str, payload: dict[str, Any], role: str) -> dict[str, Any]:
    _require_role(role, "order.qc")
    order = _order(order_id)
    if order["status"] != "qc_pending":
        raise M2Error(409, "invalid_status", f"当前状态 {ORDER_LABELS.get(order['status'])} 不能质检")
    result = str(payload.get("result") or "").lower()
    if result not in {"pass", "fail"}:
        raise M2Error(422, "invalid_field", "质检结果只能是 pass 或 fail")
    note = str(payload.get("note") or "").strip()
    quality = order["quality"]
    quality["attempts"] += 1
    if result == "pass":
        order["status"] = "qc_passed"
        quality["lastResult"] = "pass"
        quality["lastNote"] = note
        quality["history"].append({"at": _now(), "result": "pass", "note": note, "role": role})
    else:
        if rules()["quality"].get("requireNoteOnMismatch", True) and not note:
            raise M2Error(422, "note_required", "质检不通过必须填写返工原因")
        quality["reworkCount"] += 1
        quality["lastResult"] = "fail"
        quality["lastNote"] = note
        quality["history"].append({"at": _now(), "result": "fail", "note": note, "role": role})
        limit = int(rules()["quality"].get("reworkLimit", 2))
        order["status"] = "escalated" if quality["reworkCount"] > limit else "rework"
    order["updatedAt"] = _now()
    order["history"].append({
        "action": "qc_" + result, "label": "质检通过" if result == "pass" else "质检不通过",
        "at": _now(), "role": role, "from": "qc_pending", "to": order["status"], "note": note,
    })
    store().put("production_orders", order_id, order)
    _log("order", order_id, "qc_" + result, "质检通过" if result == "pass" else "质检不通过", "qc_pending", order["status"], role, note)
    return order


def ship_order(order_id: str, payload: dict[str, Any], role: str) -> dict[str, Any]:
    _require_role(role, "order.ship")
    order = _order(order_id)
    if order["status"] != "qc_passed":
        raise M2Error(409, "invalid_status", f"当前状态 {ORDER_LABELS.get(order['status'])} 不能发货")
    carrier = str(payload.get("carrier") or "").strip()
    tracking = str(payload.get("trackingNo") or payload.get("tracking_no") or "").strip()
    if not carrier or not tracking:
        raise M2Error(422, "invalid_field", "发货需要承运商与运单号（演示用合成单号）")
    order["status"] = "shipped"
    order["shipment"] = {"carrier": carrier, "trackingNo": tracking, "shippedAt": _now()}
    order["updatedAt"] = _now()
    order["history"].append({"action": "shipped", "label": "发货", "at": _now(), "role": role, "from": "qc_passed", "to": "shipped", "note": f"{carrier} {tracking}"})
    store().put("production_orders", order_id, order)
    _log("order", order_id, "shipped", "发货", "qc_passed", "shipped", role, tracking)
    return order


def settle_order(order_id: str, role: str) -> dict[str, Any]:
    _require_role(role, "order.settle")
    order = _order(order_id)
    if order["status"] != "shipped":
        raise M2Error(409, "invalid_status", f"当前状态 {ORDER_LABELS.get(order['status'])} 不能结算")
    if order.get("settlement"):
        raise M2Error(409, "already_settled", "该工艺单已结算")
    cfg = rules()
    gross = int(order["grossCents"])
    platform_fee = round(gross * float(cfg["platformFeeBps"]) / 10000)
    royalty = round(gross * float(cfg["licenseRoyaltyBps"]) / 10000)
    workshop_pay = gross - platform_fee - royalty
    settlement = {
        "grossCents": gross,
        "platformFeeCents": platform_fee,
        "licenseRoyaltyCents": royalty,
        "workshopPayoutCents": workshop_pay,
        "platformFeeBps": cfg["platformFeeBps"],
        "licenseRoyaltyBps": cfg["licenseRoyaltyBps"],
        "settledAt": _now(),
        "balanced": platform_fee + royalty + workshop_pay == gross,
    }
    entries = [
        _ledger_entry(order_id, "order", "platform_fee", "platform", platform_fee, "平台服务费 25%"),
        _ledger_entry(order_id, "order", "license_royalty", "license_owner", royalty, "纹样授权分成 10%"),
        _ledger_entry(order_id, "order", "workshop_payout", "workshop", workshop_pay, "工坊结算款"),
    ]
    order["status"] = "settled"
    order["settlement"] = settlement
    order["updatedAt"] = _now()
    order["history"].append({"action": "settled", "label": "结算分账", "at": _now(), "role": role, "from": "shipped", "to": "settled", "note": f"平台 {platform_fee} / 授权 {royalty} / 工坊 {workshop_pay} 分"})
    store().put("production_orders", order_id, order)
    campaign = _campaign(order["campaignId"])
    campaign["status"] = "completed"
    campaign["updatedAt"] = _now()
    store().put("campaigns", campaign["id"], campaign)
    _log("order", order_id, "settled", "结算分账", "shipped", "settled", role)
    return {"order": order, "ledger": entries}


def create_dispute(payload: dict[str, Any], role: str) -> dict[str, Any]:
    _require_role(role, "dispute.create")
    order = _order(str(payload.get("orderId") or payload.get("order_id") or ""))
    if order["status"] not in {"shipped", "settled"}:
        raise M2Error(409, "invalid_status", f"当前状态 {ORDER_LABELS.get(order['status'])} 不能发起争议")
    kind = str(payload.get("type") or "quality")
    if kind not in {"quality", "timing", "damage"}:
        raise M2Error(422, "invalid_field", "争议类型应为 quality / timing / damage")
    reason = str(payload.get("reason") or "").strip()
    if len(reason) < 4:
        raise M2Error(422, "invalid_field", "请填写至少 4 个字的争议说明")
    dispute = {
        "id": new_id("dsp"),
        "orderId": order["id"],
        "type": kind,
        "reason": reason,
        "status": "open",
        "resolution": "",
        "refundCents": 0,
        "createdAt": _now(),
        "resolvedAt": "",
        "createdBy": role,
    }
    store().put("disputes", dispute["id"], dispute)
    _log("dispute", dispute["id"], "created", "买家发起争议", "", "open", role, reason)
    return dispute


def resolve_dispute(dispute_id: str, payload: dict[str, Any], role: str) -> dict[str, Any]:
    _require_role(role, "dispute.resolve")
    dispute = _dispute(dispute_id)
    if dispute["status"] != "open":
        raise M2Error(409, "invalid_status", "该争议已处理")
    resolution = str(payload.get("resolution") or "")
    if resolution not in {"refund", "rework", "reject"}:
        raise M2Error(422, "invalid_field", "处理方式应为 refund / rework / reject")
    order = _order(dispute["orderId"])
    entries = []
    if resolution == "refund":
        pct = float(payload.get("refundPct", rules()["dispute"].get("defaultRefundPct", 0.3)))
        if pct <= 0 or pct > 1:
            raise M2Error(422, "invalid_field", "退款比例需在 0–1 之间")
        refund = round(int(order["grossCents"]) * pct)
        entries.append(_ledger_entry(dispute["id"], "dispute", "refund_buyer", "buyer", refund, f"争议退款 {round(pct * 100)}%"))
        entries.append(_ledger_entry(dispute["id"], "dispute", "workshop_adjust", "workshop", -refund, "工坊承担争议退款"))
        dispute["refundCents"] = refund
    elif resolution == "rework":
        order["status"] = "rework"
        order["quality"]["reworkCount"] += 1
        store().put("production_orders", order["id"], order)
    dispute["status"] = "resolved" if resolution != "reject" else "rejected"
    dispute["resolution"] = resolution
    dispute["resolvedAt"] = _now()
    dispute["resolvedBy"] = role
    dispute["note"] = str(payload.get("note") or "")
    store().put("disputes", dispute_id, dispute)
    _log("dispute", dispute_id, "resolved", {"refund": "退款结案", "rework": "返工结案", "reject": "驳回争议"}[resolution], "open", dispute["status"], role, dispute["note"])
    return {"dispute": dispute, "ledger": entries}


def cancel_campaign(campaign_id: str, payload: dict[str, Any], role: str) -> dict[str, Any]:
    _require_role(role, "campaign.cancel")
    campaign = _campaign(campaign_id)
    if campaign["status"] in {"funded", "in_production", "completed"}:
        raise M2Error(409, "invalid_status", "已成团的预售不能直接取消，请走争议流程")
    campaign["status"] = "cancelled"
    campaign["cancelReason"] = str(payload.get("reason") or "")
    campaign["updatedAt"] = _now()
    store().put("campaigns", campaign_id, campaign)
    for pledge in store().list("pledges", 500):
        if pledge["campaignId"] == campaign_id and pledge["status"] == "paid":
            pledge["status"] = "refunded"
            store().put("pledges", pledge["id"], pledge)
            _ledger_entry(pledge["id"], "pledge", "refund_buyer", "buyer", pledge["depositCents"], "未成团取消，定金原路退回")
    _log("campaign", campaign_id, "cancelled", "取消预售", campaign["status"], "cancelled", role, campaign["cancelReason"])
    return campaign


def reset_demo() -> None:
    st = store()
    for coll in ("campaigns", "pledges", "production_orders", "dispatches", "ledger", "disputes", "events"):
        for row in st.list(coll, 2000):
            st.delete(coll, row["id"])


def dashboard() -> dict[str, Any]:
    st = store()
    campaigns = st.list("campaigns")
    orders = st.list("production_orders")
    ledger = st.list("ledger")
    disputes = st.list("disputes")
    ledger_total = sum(e["amountCents"] for e in ledger)
    by_type: dict[str, int] = {}
    for entry in ledger:
        by_type[entry["type"]] = by_type.get(entry["type"], 0) + entry["amountCents"]
    return {
        "campaigns": {
            "total": len(campaigns),
            "open": len([c for c in campaigns if c["status"] == "open"]),
            "funded": len([c for c in campaigns if c["status"] in {"funded", "in_production", "completed"}]),
            "pledgedDepositCents": sum(c["pledgedDepositCents"] for c in campaigns),
        },
        "orders": {
            "total": len(orders),
            "inFlight": len([o for o in orders if o["status"] in {"created", "dispatched", "accepted", "in_progress", "qc_pending", "qc_passed", "rework"}]),
            "settled": len([o for o in orders if o["status"] == "settled"]),
            "grossCents": sum(o["grossCents"] for o in orders),
        },
        "disputes": {"total": len(disputes), "open": len([d for d in disputes if d["status"] == "open"])},
        "ledger": {"entries": len(ledger), "netCents": ledger_total, "byType": by_type},
    }


# --------------------------------------------------------------------------- #
# 一键全链路（演示与验收用；内部调用同一批业务函数，不是写死的假数据）
# --------------------------------------------------------------------------- #
def run_scenario(role: str = "admin") -> dict[str, Any]:
    reset_demo()
    steps: list[dict[str, Any]] = []

    def step(title: str, fn, *, expect_error: bool = False) -> None:
        try:
            result = fn()
            steps.append({"title": title, "ok": True, "expectError": expect_error, "result": result})
        except M2Error as exc:
            steps.append({
                "title": title, "ok": False, "expectError": expect_error,
                "status": exc.status, "error": exc.error, "message": exc.message, "extra": exc.extra,
            })

    campaign = create_campaign({
        "patternId": "moon-gate", "process": "casting", "material": "brass", "finish": "polished",
        "quantityPerUnit": 1, "params": {"wallThickness": 2.2, "undercutAngle": 4},
        "title": "月洞门 · 黄铜书签预售（合成样例）", "deadlineDays": 14,
    }, role)
    steps.append({"title": "① 创建预售活动（草稿）", "ok": True, "result": _brief_campaign(campaign)})

    campaign = open_campaign(campaign["id"], role)
    steps.append({"title": "② 开放预售", "ok": True, "result": _brief_campaign(campaign)})

    campaign = create_pledge(campaign["id"], {"backer": "支持者 A（合成）", "qty": 12}, "buyer")["campaign"]
    steps.append({"title": "③ 支持者 A 定金下单 12 份", "ok": True, "result": _brief_campaign(campaign)})

    pledge_result = create_pledge(campaign["id"], {"backer": "支持者 B（合成）", "qty": 8}, "buyer")
    campaign = pledge_result["campaign"]
    steps.append({
        "title": "④ 支持者 B 定金下单 8 份 → 达到起订量自动成团",
        "ok": True, "funded": pledge_result["funded"], "result": _brief_campaign(campaign),
    })

    order_id = campaign["productionOrderId"]
    step("⑤ 误派给不做铸造的工坊（能力匹配校验应拒绝）",
         lambda: dispatch_order(order_id, {"workshopId": "ws-jewel-02"}, "ops"), expect_error=True)
    step("⑥ 改派给具备铸造能力的工坊", lambda: dispatch_order(order_id, {"workshopId": "ws-jewel-01"}, "ops"))

    dispatch_id = _order(order_id)["dispatchId"]
    step("⑦ 工坊确认接单", lambda: respond_dispatch(dispatch_id, {"accept": True, "note": "排产 7 天"}, "workshop"))
    step("⑧ 开工", lambda: start_order(order_id, "workshop"))
    step("⑨ 提交质检", lambda: submit_qc(order_id, "ops"))
    step("⑩ 质检不通过（附返工原因）", lambda: qc_result(order_id, {"result": "fail", "note": "边角有砂眼，需补蜡重铸"}, "ops"))
    step("⑪ 返工后重新开工", lambda: start_order(order_id, "workshop"))
    step("⑫ 再次提交质检", lambda: submit_qc(order_id, "ops"))
    step("⑬ 质检通过", lambda: qc_result(order_id, {"result": "pass", "note": "抽检 5 件外观合格"}, "ops"))
    step("⑭ 发货（合成运单）", lambda: ship_order(order_id, {"carrier": "顺丰（合成）", "trackingNo": "SF-DEMO-0001"}, "ops"))
    step("⑮ 结算分账", lambda: settle_order(order_id, "finance"))

    def dispute_flow() -> dict[str, Any]:
        dispute = create_dispute({"orderId": order_id, "type": "quality", "reason": "收到后 2 件表面有轻微色差（演示数据）"}, "buyer")
        return resolve_dispute(dispute["id"], {"resolution": "refund", "refundPct": 0.3, "note": "按 30% 退款并结案"}, "finance")

    step("⑯ 买家发起争议 → 30% 退款结案", dispute_flow)

    return {
        "ok": True,
        "scenario": "m2-full-chain",
        "generatedAt": _now(),
        "steps": steps,
        "summary": {
            "steps": len(steps),
            "passed": len([s for s in steps if s.get("ok")]),
            "expectedFailures": len([s for s in steps if s.get("expectError") and not s.get("ok")]),
            "campaignId": campaign["id"],
            "orderId": order_id,
        },
        "dashboard": dashboard(),
    }


def _brief_campaign(campaign: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": campaign["id"], "title": campaign["title"], "status": campaign["status"],
        "statusLabel": STATUS_LABELS.get(campaign["status"]),
        "pledgedQty": campaign["pledgedQty"], "minBatch": campaign["minBatch"],
        "pledgedDepositCents": campaign["pledgedDepositCents"],
        "unitCents": campaign["unitCents"], "depositCentsPerUnit": campaign["depositCentsPerUnit"],
        "productionOrderId": campaign["productionOrderId"],
    }


# --------------------------------------------------------------------------- #
# HTTP 路由
# --------------------------------------------------------------------------- #
def _config_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "module": "M2 · C2M 预售与制造协同",
        "rules": rules(),
        "workshops": workshops(),
        "actors": ACTORS,
        "permissions": {k: [{"role": r, "label": ACTORS.get(r, r)} for r in v] for k, v in PERMISSIONS.items()},
        "patterns": [dict(p, sourceLabel=SOURCE_LABELS.get(p["source"], p["source"])) for p in PATTERNS],
        "processLabels": PROCESS_LABELS,
        "materialLabels": MATERIAL_LABELS,
        "finishLabels": FINISH_LABELS,
        "unitCents": UNIT_CENTS,
        "campaignStatusLabels": STATUS_LABELS,
        "orderStatusLabels": ORDER_LABELS,
        "dispatchStatusLabels": DISPATCH_LABELS,
        "flow": ["创建预售活动", "开放预售", "定金下单", "达成起订量成团", "生成工艺单", "派单（能力校验）", "工坊接单", "开工", "质检", "返工 / 放行", "发货", "结算分账", "争议处理"],
    }


def _handle(handler, method: str, path: str) -> bool:
    if not path.startswith("/api/m2/"):
        return False
    try:
        if method == "GET":
            _route_get(handler, path)
        else:
            _route_post(handler, path)
    except M2Error as exc:
        payload: dict[str, Any] = {"ok": False, "error": exc.error, "message": exc.message}
        payload.update(exc.extra)
        _send(handler, exc.status, payload)
    except ValueError as exc:
        _send(handler, 400, {"ok": False, "error": "invalid_request", "message": str(exc)})
    except Exception as exc:  # pragma: no cover - 兜底，避免 500 静默
        handler.log_message("M2 %s %s failed: %r", method, path, exc)
        _send(handler, 500, {"ok": False, "error": "internal_error", "message": "M2 内部错误"})
    return True


def _route_get(handler, path: str) -> None:
    if path in {"/api/m2/config", "/api/m2/bootstrap"}:
        _send(handler, 200, _config_payload())
        return
    if path == "/api/m2/dashboard":
        _send(handler, 200, {"ok": True, "dashboard": dashboard()})
        return
    if path == "/api/m2/campaigns":
        rows = list(reversed(store().list("campaigns")))
        _send(handler, 200, {"ok": True, "campaigns": rows, "statusLabels": STATUS_LABELS})
        return
    if path == "/api/m2/production-orders":
        rows = list(reversed(store().list("production_orders")))
        _send(handler, 200, {"ok": True, "orders": rows, "statusLabels": ORDER_LABELS})
        return
    if path == "/api/m2/dispatches":
        rows = list(reversed(store().list("dispatches")))
        _send(handler, 200, {"ok": True, "dispatches": rows, "statusLabels": DISPATCH_LABELS})
        return
    if path == "/api/m2/ledger":
        rows = list(reversed(store().list("ledger")))
        _send(handler, 200, {"ok": True, "ledger": rows, "netCents": sum(r["amountCents"] for r in rows)})
        return
    if path == "/api/m2/disputes":
        _send(handler, 200, {"ok": True, "disputes": list(reversed(store().list("disputes")))})
        return
    if path == "/api/m2/events":
        _send(handler, 200, {"ok": True, "events": list(reversed(store().list("events", 400)))})
        return
    match = CAMPAIGN_ROUTE.match(path)
    if match:
        campaign_id = match.group(1)
        campaign = _campaign(campaign_id)
        pledges = [p for p in store().list("pledges", 500) if p["campaignId"] == campaign_id]
        order = store().get("production_orders", campaign.get("productionOrderId") or "")
        _send(handler, 200, {
            "ok": True, "campaign": campaign, "pledges": pledges, "order": order,
            "statusLabels": STATUS_LABELS, "orderStatusLabels": ORDER_LABELS,
        })
        return
    match = ORDER_ROUTE.match(path)
    if match:
        order = _order(match.group(1))
        dispatch = store().get("dispatches", order.get("dispatchId") or "")
        disputes = [d for d in store().list("disputes") if d["orderId"] == order["id"]]
        refs = {order["id"], order.get("dispatchId", ""), order.get("campaignId", "")}
        refs.update(d["id"] for d in disputes)
        ledger = [e for e in store().list("ledger") if e["ref"] in refs]
        _send(handler, 200, {
            "ok": True, "order": order, "dispatch": dispatch, "disputes": disputes,
            "ledger": ledger, "statusLabels": ORDER_LABELS,
        })
        return
    _send(handler, 404, {"ok": False, "error": "not_found", "message": f"M2 无此接口：{path}"})


def _route_post(handler, path: str) -> None:
    payload = handler._read_json()
    role = str(payload.get("role") or "admin")
    if path == "/api/m2/campaigns":
        campaign = create_campaign(payload, role)
        _send(handler, 201, {"ok": True, "campaign": campaign})
        return
    if path == "/api/m2/scenario":
        _send(handler, 200, run_scenario(role))
        return
    if path == "/api/m2/demo/reset":
        reset_demo()
        _send(handler, 200, {"ok": True, "reset": True, "ts": _now()})
        return
    if path == "/api/m2/disputes":
        dispute = create_dispute(payload, role)
        _send(handler, 201, {"ok": True, "dispute": dispute})
        return
    match = ORDER_CAPABILITY.match(path)
    if match:
        _send(handler, 200, {"ok": True, **preview_capability(match.group(1), payload)})
        return
    match = CAMPAIGN_ACTION.match(path)
    if match:
        campaign_id, action = match.group(1), match.group(2)
        if action == "open":
            campaign = open_campaign(campaign_id, role)
        elif action == "pledge":
            campaign = create_pledge(campaign_id, payload, role)["campaign"]
        else:
            campaign = cancel_campaign(campaign_id, payload, role)
        _send(handler, 200, {"ok": True, "campaign": campaign})
        return
    match = ORDER_ACTION.match(path)
    if match:
        order_id, action = match.group(1), match.group(2)
        if action == "dispatch":
            result = dispatch_order(order_id, payload, role)
            _send(handler, 200, {"ok": True, **result})
        elif action == "start":
            _send(handler, 200, {"ok": True, "order": start_order(order_id, role)})
        elif action == "submit-qc":
            _send(handler, 200, {"ok": True, "order": submit_qc(order_id, role)})
        elif action == "qc":
            _send(handler, 200, {"ok": True, "order": qc_result(order_id, payload, role)})
        elif action == "ship":
            _send(handler, 200, {"ok": True, "order": ship_order(order_id, payload, role)})
        else:
            _send(handler, 200, {"ok": True, **settle_order(order_id, role)})
        return
    match = DISPATCH_ACTION.match(path)
    if match:
        _send(handler, 200, {"ok": True, **respond_dispatch(match.group(1), payload, role)})
        return
    match = DISPUTE_ACTION.match(path)
    if match:
        _send(handler, 200, {"ok": True, **resolve_dispute(match.group(1), payload, role)})
        return
    _send(handler, 404, {"ok": False, "error": "not_found", "message": f"M2 无此接口：{path}"})


def handle_get(handler, path: str) -> bool:
    return _handle(handler, "GET", path)


def handle_post(handler, path: str) -> bool:
    return _handle(handler, "POST", path)
