"""验收驾驶舱后端：平台验收项 → 服务端可复跑的静态证据。

设计要点（与前端分工明确，避免服务端请求自己造成死锁）：

* 服务端只做「静态」检查：文件存在与体积、目录素材数量、源码关键字、
  M1 人工规则基线（core.human_rule_results）、以及跑一遍 unittest。
* http / scenario 两类检查由浏览器页面发出真实请求后回填，服务端不自我请求。
* 每一轮自检都可以 POST /api/evidence/record 落库，再 POST /api/evidence/export
  生成 Markdown 证据包（写到 data/evidence/packs/），路径随响应返回，可直接交付。

验收条目定义在 config/acceptance.json（纯数据文件，换一条验收标准不用改代码）。
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonstore import JsonStore, new_id

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
PACKS_DIR = DATA_DIR / "evidence" / "packs"
FENCE = "```"
ACCEPTANCE_PATH = ROOT / "config" / "acceptance.json"

STATIC_TYPES = {"file", "filecount", "grep", "m1cases", "tests"}
CLIENT_TYPES = {"http", "scenario"}

KEY_FILES = [
    "README.md", "TEST-REPORT.md", "render.yaml", "server.py", "core.py", "store.py",
    "extensions.py", "jsonstore.py", "index.html", "app.js", "styles.css",
    "mod_m2.py", "mod_ai.py", "mod_ip.py", "mod_evidence.py",
    "config/acceptance.json", "config/m2_rules.json", "config/workshops.json",
    "pages/m2.html", "pages/m2.js", "pages/ai.html", "pages/ip.html",
    "pages/evidence.html", "pages/ui.js", "pages/shell.js", "pages/pages.css",
    "docs/B-verification.md", "docs/C-verification.md",
]

_STORE: JsonStore | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def store() -> JsonStore:
    global _STORE
    if _STORE is None:
        _STORE = JsonStore(DATA_DIR / "evidence.db", "evidence")
    return _STORE


def _send(handler, status: int, payload: dict[str, Any]) -> None:
    handler._send_json(status, payload)


class EvidenceError(Exception):
    def __init__(self, status: int, error: str, message: str):
        super().__init__(message)
        self.status = status
        self.error = error
        self.message = message


def _load_acceptance() -> dict[str, Any]:
    try:
        body = json.loads(ACCEPTANCE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EvidenceError(500, "acceptance_missing", "缺少 config/acceptance.json") from exc
    except json.JSONDecodeError as exc:
        raise EvidenceError(500, "acceptance_invalid", "config/acceptance.json 不是合法 JSON：" + str(exc)) from exc
    if not isinstance(body, dict) or not isinstance(body.get("items"), list):
        raise EvidenceError(500, "acceptance_invalid", "config/acceptance.json 缺少 items 数组")
    return body


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _resolve(rel: str) -> Path:
    target = (ROOT / rel).resolve()
    if target != ROOT and ROOT not in target.parents:
        raise EvidenceError(400, "path_denied", "路径越界：" + rel)
    return target


def _fmt_bytes(size: int) -> str:
    if size >= 1024 * 1024:
        return "%.2f MB" % (size / 1024 / 1024)
    if size >= 1024:
        return "%.1f KB" % (size / 1024)
    return str(size) + " B"


def check_file(spec: dict[str, Any]) -> dict[str, Any]:
    rel = str(spec.get("path") or "")
    minimum = int(spec.get("minBytes") or 1)
    target = _resolve(rel)
    exists = target.is_file()
    size = target.stat().st_size if exists else 0
    ok = exists and size >= minimum
    detail = ("存在，" + _fmt_bytes(size) + "（阈值 " + _fmt_bytes(minimum) + "）") if exists else "文件不存在"
    if exists and not ok:
        detail = "体积不足：" + _fmt_bytes(size) + " < " + _fmt_bytes(minimum)
    digest = _sha256(target) if exists and size < 2_000_000 else ""
    return {"ok": ok, "detail": detail, "artifact": {"path": rel, "bytes": size, "sha256": digest}}


def check_filecount(spec: dict[str, Any]) -> dict[str, Any]:
    rel = str(spec.get("dir") or "")
    ext = str(spec.get("ext") or "").lower()
    minimum = int(spec.get("min") or 1)
    target = _resolve(rel)
    files = sorted(p for p in target.rglob("*") if p.is_file() and p.suffix.lower() == ext) if target.is_dir() else []
    ok = len(files) >= minimum
    detail = "命中 " + str(len(files)) + " 个 " + ext + " 文件（阈值 " + str(minimum) + "）"
    return {"ok": ok, "detail": detail, "artifact": [{"path": _rel(p), "bytes": p.stat().st_size} for p in files[:20]]}


def check_grep(spec: dict[str, Any]) -> dict[str, Any]:
    rel = str(spec.get("path") or "")
    pattern = str(spec.get("pattern") or "")
    minimum = int(spec.get("min") or 1)
    target = _resolve(rel)
    if not target.is_file():
        return {"ok": False, "detail": "文件不存在：" + rel, "artifact": {"path": rel}}
    text = target.read_text(encoding="utf-8", errors="replace")
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        raise EvidenceError(400, "bad_pattern", "正则不合法（" + rel + "）：" + str(exc)) from exc
    hits = rx.findall(text)
    count = len(hits)
    matched_lines = [{"line": idx + 1, "text": line.strip()[:120]} for idx, line in enumerate(text.splitlines()) if rx.search(line)][:5]
    ok = count >= minimum
    return {"ok": ok, "detail": "命中 " + str(count) + " 次（阈值 " + str(minimum) + "）", "artifact": {"path": rel, "matches": matched_lines}}


def check_m1cases(spec: dict[str, Any]) -> dict[str, Any]:
    minimum = int(spec.get("minCases") or 10)
    min_blocked = int(spec.get("minBlocked") or 3)
    from core import human_rule_results

    rows = human_rule_results()
    matched = [r for r in rows if r.get("matched")]
    blocked = [r for r in rows if r.get("expected") == "blocked"]
    ok = len(rows) >= minimum and len(matched) == len(rows) and len(blocked) >= min_blocked
    detail = str(len(matched)) + "/" + str(len(rows)) + " 与人工预期一致，其中不可制造 " + str(len(blocked)) + " 例（阈值 " + str(minimum) + " 例 / " + str(min_blocked) + " blocked）"
    return {"ok": ok, "detail": detail, "artifact": {"rows": rows, "blockedIds": [r.get("id") for r in blocked]}}


def check_tests(spec: dict[str, Any]) -> dict[str, Any]:
    minimum = int(spec.get("minTests") or 10)
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    started = time.time()
    try:
        proc = subprocess.run(command, cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        out = (proc.stdout or "") + (proc.stderr or "")
        rc = proc.returncode
    except subprocess.TimeoutExpired as exc:
        out = "测试超时（300s）" + str(exc.stdout or "")
        rc = -1
    duration = round(time.time() - started, 2)
    match = re.search(r"Ran (\d+) tests? in ([\d.]+)s", out)
    ran = int(match.group(1)) if match else 0
    ok = rc == 0 and ran >= minimum
    tail = out.strip().splitlines()[-60:]
    verdict = "OK" if rc == 0 else "FAILED"
    detail = "Ran " + str(ran) + " tests，" + verdict + "，耗时 " + str(duration) + "s（阈值 " + str(minimum) + " 例且全绿）"
    return {"ok": ok, "detail": detail, "artifact": {"command": "python -m unittest discover -s tests -v", "exitCode": rc, "ran": ran, "durationSec": duration, "outputTail": tail}}


STATIC_HANDLERS = {
    "file": check_file,
    "filecount": check_filecount,
    "grep": check_grep,
    "m1cases": check_m1cases,
    "tests": check_tests,
}


def _manifest() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rel in KEY_FILES:
        target = ROOT / rel
        if target.is_file():
            rows.append({"path": rel, "bytes": target.stat().st_size, "sha256": _sha256(target)})
    media_root = ROOT / "media"
    if media_root.is_dir():
        for path in sorted(media_root.rglob("*")):
            if path.is_file():
                rows.append({"path": _rel(path), "bytes": path.stat().st_size, "sha256": _sha256(path)})
    return rows


def run_static(items: list[dict[str, Any]]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for item in items:
        for spec in item.get("checks") or []:
            kind = str(spec.get("type") or "")
            label = str(spec.get("label") or kind)
            handler = STATIC_HANDLERS.get(kind)
            if handler is None:
                checks.append({"itemId": item.get("id"), "type": kind, "label": label, "status": "deferred", "detail": "由浏览器端执行", "artifact": None})
                continue
            try:
                result = handler(spec)
                checks.append({"itemId": item.get("id"), "type": kind, "label": label, "status": "passed" if result.get("ok") else "failed", "detail": result.get("detail"), "artifact": result.get("artifact")})
            except EvidenceError as exc:
                checks.append({"itemId": item.get("id"), "type": kind, "label": label, "status": "failed", "detail": exc.message, "artifact": None})
    return {
        "ok": True,
        "generatedAt": _now(),
        "checks": checks,
        "manifest": _manifest(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "cwd": str(ROOT),
            "pid": os.getpid(),
        },
    }


def _summarize(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "ref": item.get("ref"),
        "title": item.get("title"),
        "status": item.get("status"),
        "passedChecks": item.get("passedChecks"),
        "totalChecks": item.get("totalChecks"),
    }


def export_markdown(run: dict[str, Any]) -> str:
    run_id = str(run.get("runId") or "adhoc")
    items = run.get("items") or []
    passed_items = [it for it in items if it.get("status") == "passed"]
    L: list[str] = []
    L.append("# ClawHunt #1724 · 验收证据包")
    L.append("")
    L.append("- 运行编号：" + run_id)
    L.append("- 生成时间：" + str(run.get("generatedAt") or "-"))
    L.append("- 生成方式：验收驾驶舱一键全量自检（服务端静态检查 + 浏览器真实请求）")
    L.append("- 总体结论：" + str(len(passed_items)) + "/" + str(len(items)) + " 项通过")
    L.append("- 被测服务：http://127.0.0.1:8787（同一仓库、同一进程，M1 + M2 + B + C）")
    env = run.get("environment") or {}
    L.append("- 环境：Python " + str(env.get("python") or "-") + " · " + str(env.get("platform") or "-"))
    L.append("- 说明：验收项括号编号对应 ClawHunt #1724 任务书原文的 0)~10)；示例数据全部为合成或自制。")
    L.append("")
    L.append("## 一、逐项验收")
    L.append("")
    for item in items:
        mark = "✅ 通过" if item.get("status") == "passed" else "❌ 未通过"
        L.append("### " + str(item.get("id")) + " " + str(item.get("ref")) + " " + str(item.get("title")))
        L.append("")
        L.append("- 结论：" + mark + "（" + str(item.get("passedChecks") or 0) + "/" + str(item.get("totalChecks") or 0) + " 项检查通过）")
        L.append("- 对应里程碑：" + str(item.get("milestone") or "-") + "　涉及模块：" + str(item.get("module") or "-"))
        requirement = str(item.get("requirement") or "").strip()
        if requirement:
            L.append("- 验收要求：" + requirement)
        if item.get("note"):
            L.append("- 备注：" + str(item.get("note")))
        L.append("")
        L.append("| 检查项 | 类型 | 结果 | 证据 |")
        L.append("| --- | --- | --- | --- |")
        for check in item.get("checks") or []:
            status = check.get("status")
            mark_cell = "通过" if status == "passed" else ("跳过" if status == "skipped" else "未通过")
            detail = str(check.get("detail") or "").replace("|", "/").replace("\n", " ")[:220]
            L.append("| " + str(check.get("label")) + " | " + str(check.get("type")) + " | " + mark_cell + " | " + detail + " |")
        L.append("")
    L.append("## 二、测试输出（末 40 行）")
    L.append("")
    L.append(FENCE)
    L.append("python -m unittest discover -s tests -v")
    tests = run.get("tests") or {}
    tail = tests.get("outputTail") or []
    for row in tail[-40:]:
        L.append(str(row))
    L.append(FENCE)
    L.append("")
    L.append("## 三、复跑命令")
    L.append("")
    L.append(FENCE + "bash")
    L.append("cd 1724-demo")
    L.append("python -m unittest discover -s tests -v              # 全部单元测试")
    L.append("python server.py --host 127.0.0.1 --port 8787       # 启动服务")
    L.append("curl -s -X POST http://127.0.0.1:8787/api/m2/scenario   # M2 16 步全链路")
    L.append("curl -s -X POST http://127.0.0.1:8787/api/ai/scenario   # B 服务层全链路")
    L.append("curl -s -X POST http://127.0.0.1:8787/api/ip/scenario   # C IP 管线全链路")
    L.append("# 浏览器打开 http://127.0.0.1:8787/pages/evidence.html 可一键重跑本证据包")
    L.append(FENCE)
    L.append("")
    L.append("## 四、关键文件清单（sha256）")
    L.append("")
    L.append("| 文件 | 体积 | sha256 |")
    L.append("| --- | --- | --- |")
    for row in (run.get("manifest") or [])[:120]:
        L.append("| " + str(row.get("path")) + " | " + _fmt_bytes(int(row.get("bytes") or 0)) + " | " + str(row.get("sha256"))[:16] + "… |")
    L.append("")
    L.append("---")
    L.append("本证据包由 1724-demo 的验收驾驶舱（mod_evidence.py）生成；所有数字来自当次真实执行，未通过项如实保留。")
    return "\n".join(L) + "\n"


def _list_packs() -> list[dict[str, Any]]:
    if not PACKS_DIR.is_dir():
        return []
    rows = []
    for path in sorted(PACKS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
        rows.append({
            "name": path.name,
            "bytes": path.stat().st_size,
            "path": _rel(path),
            "modifiedAt": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
        })
    return rows


def _route_get(handler, path: str) -> None:
    if path in {"/api/evidence/config", "/api/evidence/bootstrap"}:
        acceptance = _load_acceptance()
        payload = {
            "ok": True,
            "module": "evidence",
            "version": acceptance.get("version"),
            "updatedAt": acceptance.get("updatedAt"),
            "platformTask": acceptance.get("platformTask"),
            "items": acceptance.get("items"),
            "clientTypes": sorted(CLIENT_TYPES),
            "staticTypes": sorted(STATIC_TYPES),
            "modules": {
                "m1": {"label": "M1 工作站", "config": "/api/bootstrap", "health": "/api/health", "scenario": None},
                "m2": {"label": "M2 预售与制造协同", "config": "/api/m2/config", "health": "/api/health", "scenario": "/api/m2/scenario"},
                "ai": {"label": "B 企业 AI 服务层", "config": "/api/ai/config", "health": "/api/health", "scenario": "/api/ai/scenario"},
                "ip": {"label": "C 文化 IP 短剧管线", "config": "/api/ip/config", "health": "/api/health", "scenario": "/api/ip/scenario"},
            },
            "packs": _list_packs(),
        }
        _send(handler, 200, payload)
        return
    if path == "/api/evidence/dashboard":
        runs = store().list("runs")
        packs = _list_packs()
        _send(handler, 200, {"ok": True, "dashboard": {"runs": len(runs), "packs": len(packs), "latest": _summarize(runs[-1]) if runs else []}})
        return
    if path == "/api/evidence/runs":
        runs = store().list("runs")
        rows = [{
            "runId": r.get("runId"),
            "generatedAt": r.get("generatedAt"),
            "passedItems": sum(1 for it in r.get("items") or [] if it.get("status") == "passed"),
            "totalItems": len(r.get("items") or []),
            "label": r.get("label"),
        } for r in reversed(runs[-20:])]
        _send(handler, 200, {"ok": True, "runs": rows})
        return
    match = re.match(r"^/api/evidence/runs/([^/]+)$", path)
    if match:
        run = store().get("runs", match.group(1))
        if not run:
            raise EvidenceError(404, "run_not_found", "没有这条运行记录：" + match.group(1))
        _send(handler, 200, {"ok": True, "run": run})
        return
    if path == "/api/evidence/packs":
        _send(handler, 200, {"ok": True, "packs": _list_packs()})
        return
    raise EvidenceError(404, "not_found", "验收驾驶舱无此接口：" + path)


def _route_post(handler, path: str, payload: dict[str, Any]) -> None:
    if path == "/api/evidence/static-run":
        acceptance = _load_acceptance()
        items = acceptance.get("items") or []
        only = payload.get("itemIds")
        if isinstance(only, list) and only:
            wanted = {str(x) for x in only}
            items = [it for it in items if it.get("id") in wanted]
        _send(handler, 200, run_static(items))
        return
    if path == "/api/evidence/record":
        run = payload.get("run")
        if not isinstance(run, dict):
            raise EvidenceError(400, "bad_run", "run 必须是对象")
        raw = json.dumps(run, ensure_ascii=False)
        if len(raw.encode("utf-8")) > 400_000:
            raise EvidenceError(413, "run_too_large", "证据包超过 400KB，请减少检查详情")
        run_id = str(run.get("runId") or new_id("ev"))
        run["runId"] = run_id
        run.setdefault("recordedAt", _now())
        store().put("runs", run_id, run)
        _send(handler, 200, {"ok": True, "runId": run_id, "storedAt": run["recordedAt"], "runs": store().count("runs")})
        return
    if path == "/api/evidence/export":
        run_id = str(payload.get("runId") or "")
        run: dict[str, Any] | None = None
        if run_id:
            run = store().get("runs", run_id)
            if not run:
                raise EvidenceError(404, "run_not_found", "没有这条运行记录：" + run_id)
        elif isinstance(payload.get("run"), dict):
            run = payload["run"]
            run_id = str(run.get("runId") or new_id("ev"))
            run["runId"] = run_id
        else:
            raise EvidenceError(400, "missing_run", "需要 runId 或 run")
        markdown = export_markdown(run)
        PACKS_DIR.mkdir(parents=True, exist_ok=True)
        filename = "evidence-pack-" + re.sub(r"[^A-Za-z0-9_-]", "", run_id) + ".md"
        target = PACKS_DIR / filename
        target.write_text(markdown, encoding="utf-8")
        _send(handler, 200, {"ok": True, "runId": run_id, "filename": filename, "path": _rel(target), "absPath": str(target), "bytes": target.stat().st_size, "markdown": markdown})
        return
    if path == "/api/evidence/demo/reset":
        store().reset()
        removed = 0
        if PACKS_DIR.is_dir():
            for path_obj in PACKS_DIR.glob("*.md"):
                path_obj.unlink(missing_ok=True)
                removed += 1
        _send(handler, 200, {"ok": True, "reset": True, "removedPacks": removed, "ts": _now()})
        return
    raise EvidenceError(404, "not_found", "验收驾驶舱无此接口：" + path)


def _handle(handler, method: str, path: str) -> bool:
    if not path.startswith("/api/evidence/"):
        return False
    try:
        if method == "GET":
            _route_get(handler, path)
        else:
            _route_post(handler, path, handler._read_json())
    except EvidenceError as exc:
        _send(handler, exc.status, {"ok": False, "error": exc.error, "message": exc.message})
    except ValueError as exc:
        _send(handler, 400, {"ok": False, "error": "invalid_request", "message": str(exc)})
    except Exception as exc:  # pragma: no cover - 兜底，避免静默 500
        handler.log_message("evidence %s %s failed: %r", method, path, exc)
        _send(handler, 500, {"ok": False, "error": "internal_error", "message": "验收驾驶舱内部错误：" + type(exc).__name__})
    return True


def handle_get(handler, path: str) -> bool:
    return _handle(handler, "GET", path)


def handle_post(handler, path: str) -> bool:
    return _handle(handler, "POST", path)
