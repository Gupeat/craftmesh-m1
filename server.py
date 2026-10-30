from __future__ import annotations

import argparse
import json
import mimetypes
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from core import (
    ACTORS, FINISH_LABELS, MATERIAL_LABELS, MODE_LABELS, PARAM_DEFS, PATTERNS,
    PROCESS_LABELS, RULES, STATUS_LABELS, TRANSITIONS, USE_LABELS, apply_transition,
    check_request, create_order, human_rule_results, public_pattern, public_rule,
    public_transition, utcnow,
)
from store import Store

ROOT = Path(__file__).resolve().parent
MAX_BODY = 1024 * 1024
ORDER_ROUTE = re.compile(r"^/api/orders/([^/]+)$")
TRANSITION_ROUTE = re.compile(r"^/api/orders/([^/]+)/transition$")
PUBLIC_FILES = {
    "/index.html", "/app.js", "/styles.css", "/README.md", "/TEST-REPORT.md",
    "/dashboard.png", "/tests.png", "/architecture.png",
}


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class ApiHandler(BaseHTTPRequestHandler):
    store: Store
    server_version = "CraftMeshM1/1.0"
    sys_version = ""

    def log_message(self, fmt: str, *args) -> None:
        sys.stdout.write("[%s] %s\n" % (utcnow(), fmt % args))
        sys.stdout.flush()

    def _send_json(self, status: int, payload: dict) -> None:
        data = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("body_too_large")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid_json") from exc
        if not isinstance(payload, dict):
            raise ValueError("json_object_required")
        return payload

    def _serve_static(self, path: str) -> None:
        if path == "/":
            path = "/index.html"
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        clean = unquote(path)
        if clean not in PUBLIC_FILES:
            self._not_found()
            return
        target = ROOT / clean.lstrip("/")
        if not target.is_file():
            self._not_found()
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self) -> None:
        self._send_json(404, {"ok": False, "error": "not_found"})

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/health":
                self._send_json(200, {
                    "ok": True, "service": "craftmesh-m1", "version": "M1.0",
                    "ts": utcnow(), "orders": self.store.stats()["orders"],
                })
                return
            if path == "/api/bootstrap":
                self._send_json(200, {
                    "ok": True,
                    "service": "craftmesh-m1",
                    "version": "M1.0",
                    "patterns": [public_pattern(p) for p in PATTERNS],
                    "rules": [public_rule(r) for r in RULES],
                    "params": PARAM_DEFS,
                    "processes": PROCESS_LABELS,
                    "materials": MATERIAL_LABELS,
                    "finishes": FINISH_LABELS,
                    "modes": MODE_LABELS,
                    "uses": USE_LABELS,
                    "statuses": STATUS_LABELS,
                    "actors": ACTORS,
                    "transitions": [public_transition(a, s) for a, s in TRANSITIONS.items()],
                    "humanRules": human_rule_results(),
                    "orders": self.store.list(),
                    "stats": self.store.stats(),
                })
                return
            if path == "/api/orders":
                self._send_json(200, {"ok": True, "orders": self.store.list()})
                return
            match = ORDER_ROUTE.match(path)
            if match:
                order = self.store.get(unquote(match.group(1)))
                if order is None:
                    self._not_found()
                    return
                self._send_json(200, {"ok": True, "order": order})
                return
            if path.startswith("/api/"):
                self._not_found()
                return
            self._serve_static(path)
        except Exception as exc:
            self.log_message("GET %s failed: %s", path, exc)
            self._send_json(500, {"ok": False, "error": "internal_error"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/check":
                payload = self._read_json()
                result = check_request(
                    str(payload.get("patternId") or payload.get("pattern_id") or ""),
                    str(payload.get("process") or ""),
                    str(payload.get("material") or ""),
                    str(payload.get("finish") or ""),
                    payload.get("quantity", 1),
                    payload.get("params") or {},
                    str(payload.get("mode") or "recombine"),
                    str(payload.get("use") or "commercial"),
                )
                self._send_json(200, {"ok": True, "result": result})
                return
            if path == "/api/orders":
                payload = self._read_json()
                result = create_order(
                    str(payload.get("patternId") or payload.get("pattern_id") or ""),
                    str(payload.get("process") or ""),
                    str(payload.get("material") or ""),
                    str(payload.get("finish") or ""),
                    payload.get("quantity", 1),
                    payload.get("params") or {},
                    str(payload.get("mode") or "recombine"),
                    str(payload.get("role") or "designer"),
                    str(payload.get("use") or "commercial"),
                )
                if not result["ok"]:
                    status = 403 if result.get("error") == "permission_denied" else 422
                    self._send_json(status, result)
                    return
                order = result["order"]
                self.store.insert(order)
                actor = ACTORS.get(str(payload.get("role") or "designer"), {"name": "系统"})
                self.store.add_event({
                    "orderId": order["id"], "at": order["createdAt"], "action": "created",
                    "label": "创建订单", "from": "", "to": "draft",
                    "role": str(payload.get("role") or "designer"), "actor": actor["name"], "note": "",
                })
                self._send_json(201, {"ok": True, "order": self.store.get(order["id"])})
                return
            match = TRANSITION_ROUTE.match(path)
            if match:
                payload = self._read_json()
                order = self.store.get(unquote(match.group(1)))
                if order is None:
                    self._not_found()
                    return
                action = str(payload.get("action") or "")
                result = apply_transition(
                    order, action, str(payload.get("role") or "designer"),
                    str(payload.get("note") or ""),
                )
                if not result["ok"]:
                    status = 403 if result.get("error") == "permission_denied" else 409
                    if result.get("error") == "note_required":
                        status = 422
                    self._send_json(status, result)
                    return
                updated = result["order"]
                self.store.update(updated)
                event = result["event"]
                event["orderId"] = updated["id"]
                self.store.add_event(event)
                self._send_json(200, {"ok": True, "order": self.store.get(updated["id"])})
                return
            if path == "/api/demo/reset":
                payload = self._read_json()
                role = str(payload.get("role") or "")
                if role != "admin":
                    self._send_json(403, {"ok": False, "error": "permission_denied", "errors": ["仅管理员可重置演示数据"]})
                    return
                self.store.reset()
                self._send_json(200, {"ok": True, "reset": True, "ts": utcnow()})
                return
            self._not_found()
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self.log_message("POST %s failed: %s", path, exc)
            self._send_json(500, {"ok": False, "error": "internal_error"})


def make_server(host: str = "127.0.0.1", port: int = 8787, db_path: str | Path | None = None) -> ThreadingHTTPServer:
    store = Store(db_path or (ROOT / "m1.db"))
    handler = type("BoundHandler", (ApiHandler,), {"store": store})
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    return httpd


def main() -> None:
    parser = argparse.ArgumentParser(description="CraftMesh M1 reference API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--db", default=str(ROOT / "m1.db"))
    args = parser.parse_args()
    httpd = make_server(args.host, args.port, args.db)
    print(f"LISTEN http://{args.host}:{args.port}/  db={args.db}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
