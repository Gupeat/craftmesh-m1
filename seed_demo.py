#!/usr/bin/env python3
"""Seed the CraftMesh M1 demo with three synthetic orders.

Usage:
    python seed_demo.py [--base http://127.0.0.1:8788] [--force]

The demo data is synthetic. This script talks to the same public HTTP API the
browser uses, so it also acts as a small end-to-end smoke test.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


DEFAULT_PARAMS = {
    "wallThickness": 1.5,
    "undercutAngle": 3,
    "inlayGap": 0.2,
    "stoneHardness": 6,
    "engraveWidth": 0.3,
    "jointDepth": 8,
    "thickness": 20,
    "grainAngle": 0,
    "carveDepth": 1,
    "moisture": 8,
    "stoneSize": 2,
    "prongs": 4,
}


def request(base: str, method: str, path: str, payload: dict | None = None) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {body}") from exc


def build(base: str, spec: dict, workflow: list[tuple[str, str]], params: dict) -> dict:
    created = request(base, "POST", "/api/orders", {
        "patternId": spec["pattern"],
        "process": spec["process"],
        "material": spec["material"],
        "finish": spec["finish"],
        "mode": spec["mode"],
        "quantity": spec["quantity"],
        "role": "designer",
        "params": {**DEFAULT_PARAMS, **params},
    })
    order = created["order"]
    for action, role in workflow:
        request(base, "POST", f"/api/orders/{order['id']}/transition", {
            "action": action,
            "role": role,
            "note": "合成演示数据：评审备注" if action in {"request_rework", "reject_qc"} else "",
        })
    latest = request(base, "GET", f"/api/orders/{order['id']}")["order"]
    print(f"  {latest['id']}  {latest['status']:<14} {spec['label']}")
    return latest


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed CraftMesh M1 demo orders")
    parser.add_argument("--base", default="http://127.0.0.1:8788")
    parser.add_argument("--force", action="store_true", help="seed even if orders already exist")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    health = request(base, "GET", "/api/health")
    print(f"API {health.get('service')} {health.get('version')}  orders={health.get('orders')}")

    current = request(base, "GET", "/api/orders")["orders"]
    if current and not args.force:
        print(f"{len(current)} order(s) already exist; nothing to do. Use --force to append more.")
        return 0

    print("Creating three synthetic orders through POST /api/orders ...")
    build(base, {
        "pattern": "moon-gate", "process": "casting", "material": "brass",
        "finish": "polished", "mode": "copy", "quantity": 12,
        "label": "月洞门 / 铸造 / 黄铜",
    }, [("submit", "designer")], {"wallThickness": 1.6})

    build(base, {
        "pattern": "wave-lattice", "process": "inlay", "material": "silver",
        "finish": "polished", "mode": "recombine", "quantity": 6,
        "label": "海浪格 / 镶嵌 / 银",
    }, [
        ("submit", "designer"), ("accept", "reviewer"),
        ("start_production", "ops"), ("send_to_qc", "ops"),
    ], {"inlayGap": 0.18, "stoneSize": 4, "prongs": 4})

    build(base, {
        "pattern": "cloud-scroll", "process": "joinery", "material": "wood",
        "finish": "oil", "mode": "original", "quantity": 24,
        "label": "云纹 / 榫卯 / 木",
    }, [
        ("submit", "designer"), ("accept", "reviewer"),
        ("start_production", "ops"), ("send_to_qc", "ops"),
        ("pass_qc", "qc"), ("settle", "finance"),
    ], {"jointDepth": 10, "thickness": 24, "moisture": 9})

    stats = request(base, "GET", "/api/bootstrap")["stats"]
    print(f"Done. orders={stats['orders']} open={stats['open']} passed={stats['passed']} audit={stats['audit']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
