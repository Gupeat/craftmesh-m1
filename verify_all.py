#!/usr/bin/env python3
"""CraftMesh #1724 —— 一条命令跑完可复跑验收。

用法：
    python verify_all.py                 # 默认 http://127.0.0.1:8787
    python verify_all.py --base http://127.0.0.1:8787 --json out.json
    python verify_all.py --skip-tests    # 只跑场景，不跑单元测试

做的事：
1. 探活（/api/health）；
2. 跑单元测试（python -m unittest discover -s tests -v）；
3. 服务端静态验收检查（/api/evidence/static-run，复用验收驾驶舱的同一套规则）；
4. 依次跑各模块全链路场景（/api/m2|ai|ip/scenario），未启用的模块记为 SKIP；
5. 打印汇总表，任一 FAIL 时退出码为 1。

纯标准库实现，无需第三方依赖；需先启动 server.py。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
MODULES = [
    ("m2", "M2 预售与制造协同"),
    ("ai", "B 企业 AI 服务层"),
    ("ip", "C 文化 IP 短剧管线"),
]


def http_json(base, path, method="GET", payload=None, timeout=180):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"ok": False, "error": "http_error", "message": body[:300]}


def run_tests():
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    output = (proc.stdout or "") + (proc.stderr or "")
    match = re.search(r"Ran (\d+) tests?", output)
    count = int(match.group(1)) if match else 0
    tail = "\n".join([line for line in output.strip().splitlines() if line.strip()][-6:])
    return {"ok": proc.returncode == 0, "count": count, "tail": tail}


def static_checks(base):
    status, payload = http_json(base, "/api/evidence/static-run", "POST", {}, timeout=300)
    if status != 200 or not payload.get("ok"):
        return None, payload.get("message") or payload.get("error") or ("HTTP %s" % status)
    checks = payload.get("checks") or []
    payload["totals"] = {
        "passed": sum(1 for c in checks if c.get("status") == "passed"),
        "failed": sum(1 for c in checks if c.get("status") == "failed"),
        "deferred": sum(1 for c in checks if c.get("status") == "deferred"),
    }
    return payload, None


def scenario(base, module):
    status, payload = http_json(base, "/api/%s/scenario" % module, "POST", {"role": "admin"}, timeout=300)
    if status == 404:
        return {"state": "SKIP", "detail": "模块未启用（HTTP 404）"}
    if status != 200 or not payload.get("ok"):
        return {"state": "FAIL", "detail": payload.get("message") or payload.get("error") or ("HTTP %s" % status)}
    steps = payload.get("steps") or []
    summary = payload.get("summary") or {}
    bad = [s.get("title") for s in steps if not s.get("ok") and not s.get("expectError")]
    expected = summary.get("expectedFailures", 0)
    if bad:
        return {"state": "FAIL", "detail": "步骤失败：%s" % "；".join(bad[:3]), "steps": len(steps)}
    return {"state": "PASS", "detail": "%d 步完成（%d 步为预期拒绝）" % (len(steps), expected), "steps": len(steps)}


def main():
    parser = argparse.ArgumentParser(description="CraftMesh #1724 一键验收")
    parser.add_argument("--base", default="http://127.0.0.1:8787")
    parser.add_argument("--json", default="")
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()

    rows = []
    report = {"base": args.base, "startedAt": None, "rows": rows, "ok": False}

    status, health = http_json(args.base, "/api/health")
    rows.append({"name": "服务探活 /api/health", "state": "PASS" if status == 200 else "FAIL",
                 "detail": "HTTP %s" % status})
    if status != 200:
        print(json.dumps(health, ensure_ascii=False))
        _print_table(rows)
        return 1

    if not args.skip_tests:
        tests = run_tests()
        rows.append({"name": "单元测试 unittest", "state": "PASS" if tests["ok"] else "FAIL",
                     "detail": "%d 个测试" % tests["count"]})
        report["tests"] = tests

    statics, err = static_checks(args.base)
    if statics is None:
        rows.append({"name": "静态验收检查", "state": "FAIL", "detail": str(err)[:160]})
    else:
        totals = statics.get("totals") or {}
        passed = totals.get("passed", 0)
        failed = totals.get("failed", 0)
        deferred = totals.get("deferred", 0)
        rows.append({"name": "静态验收检查", "state": "PASS" if failed == 0 else "FAIL",
                     "detail": "%d 通过 / %d 失败 / %d 待测（共 %d 条）" % (passed, failed, deferred, passed + failed + deferred)})
        report["static"] = statics

    for module, label in MODULES:
        result = scenario(args.base, module)
        rows.append({"name": label + " 全链路场景", "state": result["state"], "detail": result["detail"]})
        report["scenarios"] = report.get("scenarios") or {}
        report["scenarios"][module] = result

    report["ok"] = all(r["state"] in ("PASS", "SKIP") for r in rows)
    _print_table(rows)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print("\n报告已写入 %s" % args.json)
    return 0 if report["ok"] else 1


def _print_table(rows):
    name_width = max(len(r["name"]) for r in rows) + 2
    print("")
    print("CraftMesh #1724 · 一键验收结果")
    print("-" * (name_width + 74))
    for row in rows:
        print("%s %s  %s" % (row["state"].ljust(6), row["name"].ljust(name_width), row["detail"]))
    print("-" * (name_width + 74))
    bad = [r for r in rows if r["state"] == "FAIL"]
    print("结论：%s" % ("全部通过" if not bad else "%d 项失败，见上表" % len(bad)))


if __name__ == "__main__":
    sys.exit(main())
