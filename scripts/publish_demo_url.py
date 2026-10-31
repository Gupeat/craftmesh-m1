#!/usr/bin/env python3
"""Publish the current localhost.run URL to GitHub Pages.

The stable entry is https://gupeat.github.io/craftmesh-m1/ ; this script updates
docs/live.json (served by GitHub Pages) whenever the free tunnel address changes,
so the stable entry can always find the live demo.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIVE = ROOT / "docs" / "live.json"
DEFAULT_REPO = "Gupeat/craftmesh-m1"
HOME = pathlib.Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or ".")
TOKEN_FILE = HOME / ".config" / "craftmesh" / "gh_token"
API = "https://api.github.com"


def load_live() -> dict:
    try:
        return json.loads(LIVE.read_text(encoding="utf-8"))
    except Exception:
        return {"url": "", "status": "offline", "updatedAt": ""}


def write_live(url: str, status: str) -> dict:
    data = {
        "url": url.rstrip("/"),
        "status": status,
        "updatedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "note": "Stable entry is GitHub Pages; this file is updated by scripts/publish_demo_url.py when the tunnel address changes.",
    }
    LIVE.parent.mkdir(parents=True, exist_ok=True)
    LIVE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def request(method: str, url: str, token: str, body: dict | None = None) -> dict:
    raw = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, method=method, data=raw)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "craftmesh-live-url")
    if raw is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def push(token: str, repo: str, data: dict, branch: str = "main") -> str | None:
    path = "docs/live.json"
    url = f"{API}/repos/{repo}/contents/{path}"
    remote = None
    try:
        remote = request("GET", url + "?ref=" + branch, token)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    payload = {
        "message": "Update live demo URL (" + (data.get("status") or "unknown") + ")",
        "content": base64.b64encode((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if remote and remote.get("sha"):
        payload["sha"] = remote["sha"]
    for attempt in range(3):
        try:
            out = request("PUT", url, token, payload)
            return out.get("commit", {}).get("sha")
        except urllib.error.HTTPError as exc:
            # A concurrent commit may move the file; refresh sha and retry.
            if exc.code in (409, 422) and attempt < 2:
                remote = request("GET", url + "?ref=" + branch, token)
                payload["sha"] = remote["sha"]
                continue
            raise
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="")
    parser.add_argument("--status", default="online", choices=["online", "offline"])
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--token", default="")
    parser.add_argument("--local-only", action="store_true")
    args = parser.parse_args()

    old = load_live()
    url = (args.url or old.get("url") or "").rstrip("/")
    data = write_live(url, args.status)
    print(json.dumps({"ok": True, "local": data}, ensure_ascii=False))
    if args.local_only:
        return 0
    token = args.token or os.environ.get("GITHUB_TOKEN", "")
    if not token and TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token:
        print("no GITHUB_TOKEN; docs/live.json updated locally only", file=sys.stderr)
        return 0
    try:
        sha = push(token, args.repo, data)
        print(json.dumps({"ok": True, "pushed": bool(sha), "commit": sha}, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 - keep tunnel alive even if publishing fails
        print("publish failed: " + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
