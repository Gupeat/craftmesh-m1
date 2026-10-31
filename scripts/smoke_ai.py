import json, os, sys, traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
db = ROOT.parents[1] / ".scratch" / "ai_smoke.db"
db.parent.mkdir(parents=True, exist_ok=True)
if db.exists():
    db.unlink()
os.environ["CRAFTMESH_AI_DB"] = str(db)

import mod_ai as ai

def show(label, fn):
    try:
        value = fn()
        print("OK", label, json.dumps(value, ensure_ascii=False)[:500])
        return value
    except Exception as exc:
        print("FAIL", label, type(exc).__name__, str(exc))
        traceback.print_exc()
        return None

show("reset", lambda: ai.reset_demo("admin"))
show("switch", lambda: ai.switch_industry("woodcraft", "ops")["industry"]["id"])
cfg = show("config", lambda: ai.get_config("woodcraft", "ops"))
if cfg:
    print("counts", cfg["counts"], "templateCount", len(cfg["workflowTemplates"]), "role", cfg["role"])
doc = show("write_doc", lambda: ai.write_knowledge({
    "id": "kb-wd-smoke", "title": "户外木作含水率与木蜡油养护（冒烟）",
    "industry": "woodcraft", "version": "v1.0", "status": "published",
    "content": "户外木作推荐使用黑胡桃、白蜡木或柚木。板材含水率应控制在 8%–10%。\n\n木蜡油采用两底两面，每遍间隔 4–6 小时，完成面 24 小时可轻用。",
}, "ops"))
if doc:
    print("doc chunks", doc["chunkCount"], [c["text"][:20] for c in doc["chunks"]])
show("search", lambda: ai.search_knowledge("户外餐桌 木蜡油 涂几遍 含水率", "woodcraft", 3, "ops"))
session = show("session", lambda: ai.create_session({"industry": "woodcraft", "title": "冒烟会话"}, "ops"))
if session:
    show("msg1", lambda: ai.send_session_message(session["id"], {"content": "户外餐桌的木蜡油要涂几遍？含水率控制在多少？"}, "ops"))
    m2 = show("msg2", lambda: ai.send_session_message(session["id"], {"content": "另外请登记线索：联系人 周先生，邮箱 zhou@example.com，预算 8 万，想做黑胡桃户外餐桌"}, "ops"))
    if m2:
        print("  intent", m2.get("intent"), "tools", [(c.get("tool"), c.get("ok"), c.get("resultSummary")) for c in m2.get("toolCalls", [])])
    show("session_get", lambda: len(ai.get_session(session["id"])["messages"]))
show("inquiry", lambda: ai.create_inquiry({"name": "林女士", "email": "lin@example.com", "country": "CN", "interest": "白蜡木书柜定制", "budget": "120000", "message": "希望 11 月上门复尺"}, "buyer"))
wf = show("workflow", lambda: ai.create_workflow({"templateId": "wf-wd-inquiry", "name": "冒烟工作流", "industry": "woodcraft"}, "ops"))
if wf:
    run1 = show("run_ok", lambda: {k: v for k, v in ai.run_workflow(wf["id"], {"input": {"name": "王先生", "email": "wang@example.com", "country": "CN", "interest": "黑胡桃餐桌 2.2 米", "budget": "200000", "lang": "zh"}}, "ops").items() if k in ("id", "status", "grade", "leadId", "durationMs", "failedStep")})
    if run1:
        full = ai.store().get("runs", run1["id"])
        print("  run1 detail", [(s["name"], s["ok"], s.get("detail"), s.get("error")) for s in full["steps"]])
    run2 = show("run_missing_email", lambda: {k: v for k, v in ai.run_workflow(wf["id"], {"input": {"name": "陈先生", "country": "CN", "interest": "白蜡木书柜", "budget": "60000"}}, "ops").items() if k in ("id", "status", "failedStep", "attempt")})
    if run2:
        show("retry", lambda: {k: v for k, v in ai.retry_run(run2["id"], {"input": {"email": "chen@example.com", "lang": "zh"}}, "ops").items() if k in ("id", "status", "attempt", "retryOf", "grade", "leadId")})
show("site_ja", lambda: {k: v for k, v in ai.get_site("ja", "woodcraft").items() if k in ("lang", "label")})
show("seo", lambda: {k: ai.get_seo("zh", "woodcraft")["seo"][k] for k in ("score", "coverage")})
show("handbook", lambda: {k: ai.get_fde_handbook()[k] for k in ("title", "sections", "chars")})
scenario = show("scenario", ai.run_scenario)
if scenario:
    print("summary", json.dumps(scenario["summary"], ensure_ascii=False))
    for s in scenario["steps"]:
        print(("  PASS " if s["ok"] else "  -----"), s["title"], "|", s.get("error", ""), s.get("message", "")[:90])
    second = [s for s in scenario["steps"] if "二轮" in s["title"]][0]
    print("  scenario second tool calls", json.dumps(second.get("result", {}).get("toolCalls", []), ensure_ascii=False)[:600])
