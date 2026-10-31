#!/usr/bin/env python3
"""Package the current CraftMesh #1724 delivery as a single source zip.

Only source, configuration, documentation and self-made media are included.
Runtime databases, evidence run records, logs, caches and scratch probes are
excluded so the archive is reproducible and safe to publish.

Usage:
    python make_source_bundle.py
Writes:
    downloads/craftmesh-1724-source.zip
    downloads/craftmesh-1724-source.zip.sha256
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "downloads"
OUT_ZIP = OUT_DIR / "craftmesh-1724-source.zip"
OUT_SHA = OUT_DIR / "craftmesh-1724-source.zip.sha256"

INCLUDE_DIRS = ("pages", "config", "tests", "docs", "media", "scripts")
INCLUDE_SUFFIX = {
    ".py", ".js", ".css", ".html", ".json", ".md", ".svg", ".wav", ".srt",
    ".txt", ".yaml", ".yml", ".png", ".ps1",
}
ROOT_FILES = (
    "README.md", "TEST-REPORT.md", "Dockerfile", ".dockerignore", ".gitignore",
    "render.yaml", "requirements.txt",
)
EXCLUDE_PARTS = {".git", ".scratch", "__pycache__", "data", "downloads", "node_modules"}
EXCLUDE_SUFFIX = {".db", ".pyc", ".log"}
EXCLUDE_NAMES = {".probe_core.py", ".scratch-probe-ai.py"}


def collect() -> list[Path]:
    files: list[Path] = []
    for name in ROOT_FILES:
        path = ROOT / name
        if path.is_file():
            files.append(path)
    for path in ROOT.glob("*.py"):
        if path.name in EXCLUDE_NAMES:
            continue
        files.append(path)
    for folder in INCLUDE_DIRS:
        base = ROOT / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel_parts = path.relative_to(ROOT).parts
            if any(part in EXCLUDE_PARTS for part in rel_parts):
                continue
            if path.suffix.lower() in EXCLUDE_SUFFIX:
                continue
            if path.suffix.lower() not in INCLUDE_SUFFIX and path.name not in (".dockerignore", ".gitignore"):
                continue
            files.append(path)
    # A deterministic order makes the archive easy to diff between builds.
    return sorted(set(files), key=lambda p: str(p.relative_to(ROOT)).lower())


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = collect()
    manifest = []
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        data = path.read_bytes()
        manifest.append({"path": rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    summary = {
        "name": "craftmesh-1724-source",
        "task": "ClawHunt #1724 / A+B+C runnable delivery",
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fileCount": len(manifest),
        "totalBytes": sum(item["bytes"] for item in manifest),
        "note": "All business data is synthetic; media is self-made. Databases, logs and scratch files are excluded.",
        "files": manifest,
    }
    with zipfile.ZipFile(OUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for item, path in zip(manifest, files):
            info = zipfile.ZipInfo(item["path"], date_time=(2026, 10, 31, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())
        zf.writestr("SOURCE-MANIFEST.json", json.dumps(summary, ensure_ascii=False, indent=2))
    digest = hashlib.sha256(OUT_ZIP.read_bytes()).hexdigest()
    OUT_SHA.write_text(digest + "  " + OUT_ZIP.name + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "zip": str(OUT_ZIP),
        "bytes": OUT_ZIP.stat().st_size,
        "sha256": digest,
        "files": len(manifest),
        "sourceBytes": summary["totalBytes"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
