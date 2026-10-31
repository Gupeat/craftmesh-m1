"""Module C · 文化 IP 短剧管线（原创纸影短剧《山谷回声》）。

真实可运行的纵切：
  角色手册 → 剧本节拍 → 12 格分镜 → 自制 SVG 场景 / SAPI 配音 / SRT 字幕
  → 浏览器样片播放器 → 内容审核台（规则 + 留痕）→ 授权草稿 / 衍生品规格。

所有数据、角色、文案、规则、合同与 SKU 均为合成样例；所有“智能”判断均由本地
确定性规则引擎完成，不调用外部模型或外部 API。
"""
from __future__ import annotations

import json
import re
import threading
import traceback
import wave
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from jsonstore import JsonStore, new_id

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CONFIG_PATH = ROOT / "config" / "ip_story.json"
MEDIA_DIR = ROOT / "media"
DB_PATH = DATA_DIR / "ip.db"

MODULE_ID = "ip"
MODULE_NAME = "文化 IP 短剧管线"
SCENARIO_NAME = "ip-full-chain"
COLL_REVIEWS = "reviews"
COLL_LICENSES = "licenses"
COLL_EVENTS = "events"
MAX_BODY = 1_000_000

CAPABILITY_FALLBACK = {
    "content.review": "内容审核",
    "license.preview": "生成授权草稿",
    "derivative.publish": "发布衍生品",
    "asset.validate": "素材校验",
    "demo.reset": "重置演示数据",
}


class IpError(Exception):
    def __init__(self, status: int, error: str, message: str, extra: dict | None = None):
        super().__init__(message)
        self.status = status
        self.error = error
        self.message = message
        self.extra = extra or {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _send(handler, status: int, payload: dict) -> None:
    handler._send_json(status, payload)


_store_lock = threading.RLock()
_store: JsonStore | None = None


def store() -> JsonStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                _store = JsonStore(DB_PATH, MODULE_ID)
    return _store


_cfg_lock = threading.RLock()
_cfg_cache: dict | None = None
_cfg_token: tuple[int, int] | None = None


def config() -> dict:
    global _cfg_cache, _cfg_token
    with _cfg_lock:
        stat = CONFIG_PATH.stat()
        token = (stat.st_mtime_ns, stat.st_size)
        if _cfg_cache is not None and _cfg_token == token:
            return _cfg_cache
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IpError(500, "config_invalid", f"配置文件读取失败：{exc}") from exc
        _validate_config(data)
        _cfg_cache = data
        _cfg_token = token
        return data


def _validate_config(cfg: dict) -> None:
    for key in ("module", "characters", "story", "shots", "media", "review", "license", "derivatives", "permissions", "actors"):
        if key not in cfg:
            raise IpError(500, "config_invalid", f"配置缺少字段：{key}")
    if len(cfg["characters"]) != 2:
        raise IpError(500, "config_invalid", "角色手册必须恰好包含两个原创角色")
    if len(cfg["shots"]) < 10:
        raise IpError(500, "config_invalid", "分镜不得少于 10 格")
    if len(cfg["story"].get("beats", [])) < 6:
        raise IpError(500, "config_invalid", "剧本节拍不得少于 6 场")
    if not isinstance(cfg["media"].get("minMs"), int) or not isinstance(cfg["media"].get("maxMs"), int):
        raise IpError(500, "config_invalid", "media.minMs / maxMs 必须是整数")
    if cfg["media"]["minMs"] >= cfg["media"]["maxMs"]:
        raise IpError(500, "config_invalid", "media 时长上下限不合法")


def _clean_text(value, limit: int = 1000) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text.strip()[:limit]


def _single_line(value, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", _clean_text(value, limit * 2))
    return text[:limit].strip()


def actor_label(role: str) -> str:
    cfg = config()
    return str(cfg.get("actors", {}).get(role) or role or "管理员")


def capability_label(capability: str) -> str:
    cfg = config()
    labels = cfg.get("capabilities") or {}
    return str(labels.get(capability) or CAPABILITY_FALLBACK.get(capability) or capability)


def _require_role(role: str, capability: str) -> None:
    cfg = config()
    allowed = list(cfg.get("permissions", {}).get(capability, []))
    if role not in allowed:
        raise IpError(
            403,
            "forbidden",
            f"角色 {actor_label(role)} 不能执行 {capability_label(capability)}",
            {"capability": capability, "allowedRoles": allowed},
        )


def _log(action: str, ref_id: str = "", label: str = "", role: str = "", note: str = "", extra: dict | None = None) -> None:
    doc = {
        "id": new_id("evt"),
        "at": _now(),
        "module": MODULE_ID,
        "action": action,
        "refId": ref_id,
        "label": label,
        "role": role,
        "actor": actor_label(role) if role else "",
        "note": note,
    }
    if extra:
        doc.update(extra)
    store().put(COLL_EVENTS, doc["id"], doc)


def _read_json(handler) -> dict:
    """Independent body reader with explicit 400-shaped errors."""
    raw_length = handler.headers.get("Content-Length") or "0"
    try:
        length = int(raw_length)
    except (TypeError, ValueError) as exc:
        raise IpError(400, "invalid_request", "Content-Length 不合法") from exc
    if length < 0:
        raise IpError(400, "invalid_request", "Content-Length 不合法")
    if length > MAX_BODY:
        raise IpError(413, "body_too_large", "请求体超过 1MB 限制")
    raw = handler.rfile.read(length) if length else b"{}"
    if not raw.strip():
        raw = b"{}"
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IpError(400, "invalid_json", "请求体必须是合法的 JSON 对象") from exc
    if not isinstance(payload, dict):
        raise IpError(400, "invalid_request", "请求体必须是 JSON 对象")
    return payload


def _query_int(handler, key: str, default: int, low: int, high: int) -> int:
    try:
        values = parse_qs(urlparse(getattr(handler, "path", "")).query).get(key)
        value = int(values[0]) if values else default
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def duration_report(cfg: dict | None = None) -> dict:
    cfg = cfg or config()
    shots = cfg["shots"]
    total = 0
    issues: list[str] = []
    for shot in shots:
        ms = shot.get("durationMs")
        if not isinstance(ms, int) or isinstance(ms, bool) or ms <= 0:
            issues.append(f"镜号 {shot.get('no', '?')} 时长不是正整数")
            continue
        if ms < 800:
            issues.append(f"镜号 {shot.get('no', '?')} 时长过短（{ms}ms）")
        total += ms
    min_ms = int(cfg["media"]["minMs"])
    max_ms = int(cfg["media"]["maxMs"])
    ok = not issues and min_ms <= total <= max_ms
    if not (min_ms <= total <= max_ms):
        issues.append(f"总时长 {total / 1000:.1f}s 不在 {min_ms / 1000:.0f}–{max_ms / 1000:.0f}s 内")
    return {
        "totalMs": total,
        "totalSeconds": round(total / 1000, 1),
        "minMs": min_ms,
        "maxMs": max_ms,
        "minSeconds": round(min_ms / 1000, 1),
        "maxSeconds": round(max_ms / 1000, 1),
        "shotCount": len(shots),
        "ok": ok,
        "issues": issues,
    }


def wav_meta(path: Path) -> dict | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            return {
                "durationMs": round(frames / rate * 1000) if rate else 0,
                "sampleRate": rate,
                "channels": channels,
                "sampleWidth": width,
                "frames": frames,
                "bytes": path.stat().st_size,
            }
    except (wave.Error, OSError):
        return None


def srt_meta(path: Path) -> dict | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    blocks = [block for block in re.split(r"\n\s*\n", text.strip()) if block.strip()]
    return {
        "bytes": path.stat().st_size,
        "cues": len(blocks),
        "lines": len(text.splitlines()),
        "firstCue": blocks[0] if blocks else "",
    }


def _media_generated_at() -> str | None:
    path = MEDIA_DIR / "manifest.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("generatedAt")
    except (OSError, json.JSONDecodeError):
        return None


def asset_catalog(simulate_missing_audio: bool = False) -> dict:
    cfg = config()
    entries: list[dict] = []

    def add(kind: str, label: str, url: str, path: Path, shot: dict | None = None, **extra):
        exists = path.exists() and path.is_file()
        if simulate_missing_audio and url == "/media/voice/shot-01.wav":
            exists = False
        item = {
            "kind": kind,
            "label": label,
            "url": url,
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "exists": exists,
            "bytes": path.stat().st_size if exists else 0,
            "shot": shot.get("no") if shot else None,
        }
        item.update(extra)
        entries.append(item)
        return item

    for shot in cfg["shots"]:
        no = shot["no"]
        add("scene", f"分镜 {no:02d} 场景卡", shot["svg"], ROOT / shot["svg"].lstrip("/"), shot)
        audio_path = ROOT / shot["audio"].lstrip("/")
        meta = wav_meta(audio_path) if not (simulate_missing_audio and no == 1) else None
        add("voice", f"分镜 {no:02d} 配音", shot["audio"], audio_path, shot,
            durationMs=(meta or {}).get("durationMs"),
            sampleRate=(meta or {}).get("sampleRate"),
            channels=(meta or {}).get("channels"),
            fitsSlot=bool(meta and meta["durationMs"] <= shot["durationMs"]))
        srt_path = ROOT / shot["srt"].lstrip("/")
        smeta = srt_meta(srt_path)
        add("subtitle", f"分镜 {no:02d} 字幕", shot["srt"], srt_path, shot,
            cues=(smeta or {}).get("cues"), lines=(smeta or {}).get("lines"))

    for char in cfg["characters"]:
        add("character", f"{char['name']} · 角色设定卡", char["portrait"], ROOT / char["portrait"].lstrip("/"))
    add("poster", "《山谷回声》主视觉", "/media/ip-poster.svg", MEDIA_DIR / "ip-poster.svg")

    master_audio = ROOT / cfg["media"]["masterAudio"].lstrip("/")
    master_meta = wav_meta(master_audio)
    add("master_audio", "时间轴总配音", cfg["media"]["masterAudio"], master_audio,
        durationMs=(master_meta or {}).get("durationMs"),
        sampleRate=(master_meta or {}).get("sampleRate"),
        channels=(master_meta or {}).get("channels"))
    master_srt = ROOT / cfg["media"]["masterSrt"].lstrip("/")
    msmeta = srt_meta(master_srt)
    add("master_subtitle", "总字幕 SRT", cfg["media"]["masterSrt"], master_srt,
        cues=(msmeta or {}).get("cues"), lines=(msmeta or {}).get("lines"))

    missing = [item for item in entries if not item["exists"]]
    voices = [item for item in entries if item["kind"] == "voice"]
    report = duration_report(cfg)
    checks = [
        {"id": "scenes", "label": "12 张场景 SVG 存在", "ok": all(i["exists"] for i in entries if i["kind"] == "scene"),
         "detail": f"{sum(1 for i in entries if i['kind'] == 'scene')} 张"},
        {"id": "voices", "label": "12 段配音 WAV 存在且可读", "ok": all(i["exists"] and i.get("durationMs") for i in voices),
         "detail": f"{sum(1 for i in voices if i['exists'] and i.get('durationMs'))} / 12"},
        {"id": "voice_slot", "label": "每段配音不超出分镜时长", "ok": all(i.get("fitsSlot") for i in voices),
         "detail": "逐镜校验"},
        {"id": "subtitles", "label": "12 段 SRT + 总字幕存在", "ok": all(i["exists"] for i in entries if i["kind"] == "subtitle") and bool(msmeta),
         "detail": f"总字幕 {((msmeta or {}).get('cues') or 0)} 条"},
        {"id": "characters", "label": "双角色设定卡存在", "ok": all(i["exists"] for i in entries if i["kind"] == "character"), "detail": "2 张"},
        {"id": "master_audio", "label": "总配音时长等于分镜时间轴", "ok": bool(master_meta) and abs(master_meta["durationMs"] - report["totalMs"]) <= int(cfg["media"].get("durationToleranceMs", 120)),
         "detail": f"{((master_meta or {}).get('durationMs') or 0)}ms / {report['totalMs']}ms"},
    ]
    summary = {
        "total": len(entries),
        "present": sum(1 for item in entries if item["exists"]),
        "missing": len(missing),
        "scenes": sum(1 for item in entries if item["kind"] == "scene"),
        "voices": len(voices),
        "subtitles": sum(1 for item in entries if item["kind"] == "subtitle"),
        "characters": sum(1 for item in entries if item["kind"] == "character"),
        "audioTotalMs": sum((item.get("durationMs") or 0) for item in voices),
        "masterAudioMs": (master_meta or {}).get("durationMs"),
        "sampleRates": sorted({item.get("sampleRate") for item in voices if item.get("sampleRate")}),
        "simulatedMissing": simulate_missing_audio,
    }
    return {
        "assets": entries,
        "missing": missing,
        "checks": checks,
        "summary": summary,
        "generatedAt": _media_generated_at(),
    }


def build_manifest() -> dict:
    cfg = config()
    report = duration_report(cfg)
    shots: list[dict] = []
    start = 0
    warnings: list[str] = []
    for shot in cfg["shots"]:
        svg_path = ROOT / shot["svg"].lstrip("/")
        audio_path = ROOT / shot["audio"].lstrip("/")
        srt_path = ROOT / shot["srt"].lstrip("/")
        meta = wav_meta(audio_path)
        smeta = srt_meta(srt_path)
        end = start + shot["durationMs"]
        audio_ok = bool(meta)
        fits = bool(meta and meta["durationMs"] <= shot["durationMs"])
        if not audio_ok:
            warnings.append(f"分镜 {shot['no']:02d} 缺少或无法读取配音")
        elif not fits:
            warnings.append(f"分镜 {shot['no']:02d} 配音 {meta['durationMs']}ms 超出分镜 {shot['durationMs']}ms")
        if not svg_path.exists():
            warnings.append(f"分镜 {shot['no']:02d} 缺少场景 SVG")
        if not smeta:
            warnings.append(f"分镜 {shot['no']:02d} 缺少 SRT")
        shots.append({
            "index": shot["no"],
            "no": shot["no"],
            "id": shot["id"],
            "scene": shot["scene"],
            "sceneType": shot["sceneType"],
            "startMs": start,
            "endMs": end,
            "durationMs": shot["durationMs"],
            "caption": shot["caption"],
            "speaker": shot["speaker"],
            "characters": shot.get("characters", []),
            "visual": shot.get("visual", ""),
            "camera": shot.get("camera", ""),
            "sfx": shot.get("sfx", ""),
            "svg": shot["svg"],
            "audio": shot["audio"],
            "srt": shot["srt"],
            "audioDurationMs": (meta or {}).get("durationMs"),
            "audioSampleRate": (meta or {}).get("sampleRate"),
            "audioFitsSlot": fits,
            "audioBytes": (meta or {}).get("bytes", 0),
            "svgBytes": svg_path.stat().st_size if svg_path.exists() else 0,
            "srtCues": (smeta or {}).get("cues", 0),
            "srtBytes": (smeta or {}).get("bytes", 0),
            "assetsOk": bool(meta and fits and svg_path.exists() and smeta),
        })
        start = end

    master_audio = ROOT / cfg["media"]["masterAudio"].lstrip("/")
    master_meta = wav_meta(master_audio)
    master_srt = srt_meta(ROOT / cfg["media"]["masterSrt"].lstrip("/"))
    tolerance = int(cfg["media"].get("durationToleranceMs", 120))
    master_ok = bool(master_meta) and abs(master_meta["durationMs"] - report["totalMs"]) <= tolerance
    if not master_ok:
        warnings.append("总配音缺失或与分镜时间轴不一致")
    return {
        "module": MODULE_ID,
        "title": cfg["story"]["title"],
        "voiceName": cfg["media"]["voiceName"],
        "totalMs": report["totalMs"],
        "totalSeconds": report["totalSeconds"],
        "minMs": report["minMs"],
        "maxMs": report["maxMs"],
        "durationOk": report["ok"],
        "shots": shots,
        "shotCount": len(shots),
        "master": {
            "audio": cfg["media"]["masterAudio"],
            "srt": cfg["media"]["masterSrt"],
            "durationMs": (master_meta or {}).get("durationMs"),
            "sampleRate": (master_meta or {}).get("sampleRate"),
            "channels": (master_meta or {}).get("channels"),
            "bytes": (master_meta or {}).get("bytes", 0),
            "srtCues": (master_srt or {}).get("cues", 0),
            "ok": master_ok,
        },
        "audioTotalMs": sum((shot.get("audioDurationMs") or 0) for shot in shots),
        "allAudioFits": all(shot["audioFitsSlot"] for shot in shots),
        "assetsOk": all(shot["assetsOk"] for shot in shots) and master_ok,
        "warnings": warnings,
        "generatedAt": _media_generated_at() or _now(),
    }


def story_payload() -> dict:
    cfg = config()
    report = duration_report(cfg)
    shots: list[dict] = []
    start = 0
    for shot in cfg["shots"]:
        item = dict(shot)
        item["startMs"] = start
        item["endMs"] = start + shot["durationMs"]
        start = item["endMs"]
        shots.append(item)
    required = ("no", "scene", "durationMs", "visual", "camera", "characters", "speaker", "caption", "sfx", "sceneType", "svg", "audio", "srt")
    field_issues = []
    for shot in cfg["shots"]:
        missing = [key for key in required if key not in shot or shot[key] in (None, "")]
        if missing:
            field_issues.append({"no": shot.get("no"), "missing": missing})
    covered: list[int] = []
    for beat in cfg["story"].get("beats", []):
        covered.extend(beat.get("shots", []))
    checks = [
        {"id": "shot_count", "label": "分镜不少于 10 格", "ok": len(shots) >= 10, "detail": f"{len(shots)} 格"},
        {"id": "shot_fields", "label": "每格字段完整", "ok": not field_issues, "detail": "镜号 / 场景 / 时长 / 画面 / 镜头 / 角色 / 字幕 / 音效"},
        {"id": "beats", "label": "剧本 6–8 场且覆盖全部分镜", "ok": 6 <= len(cfg["story"].get("beats", [])) <= 8 and sorted(covered) == list(range(1, len(shots) + 1)), "detail": f"{len(cfg['story'].get('beats', []))} 场 / {len(shots)} 格"},
        {"id": "duration", "label": "总时长 30–45 秒", "ok": report["ok"], "detail": f"{report['totalSeconds']}s"},
    ]
    return {
        "story": cfg["story"],
        "characters": cfg["characters"],
        "shots": shots,
        "beats": cfg["story"].get("beats", []),
        "duration": report,
        "checks": checks,
        "shotFields": list(required),
        "fieldIssues": field_issues,
    }


def characters_payload() -> dict:
    cfg = config()
    return {
        "characters": cfg["characters"],
        "count": len(cfg["characters"]),
        "actors": cfg.get("actors", {}),
        "canon": {
            "naming": "远视 / 远听，均为本模块原创角色",
            "visual": "深青 + 米白 + 朱砂；纸影剪影与几何纸纹，无真人照片、无外部素材",
            "voice": cfg["media"]["voiceName"],
        },
    }


def _rule_hits(rule: dict, text: str) -> list[str]:
    if any(token and token in text for token in rule.get("negations", [])):
        return []
    if any(token and token in text for token in rule.get("exemptIfPresent", [])):
        return []
    if rule.get("type") == "missing":
        if len(text) < int(rule.get("minLength", 0)):
            return []
        if not any(keyword in text for keyword in rule.get("keywords", [])):
            return ["缺少：" + " / ".join(rule.get("keywords", []))]
        return []
    return [keyword for keyword in rule.get("keywords", []) if keyword and keyword in text]


def review_text(text, target: str = "", role: str = "admin") -> dict:
    _require_role(role, "content.review")
    cfg = config()
    spec = cfg["review"]
    cleaned = _clean_text(text, int(spec.get("maxTextLength", 1000)) + 1)
    min_len = int(spec.get("minTextLength", 4))
    max_len = int(spec.get("maxTextLength", 1000))
    if len(cleaned) < min_len:
        raise IpError(422, "text_too_short", f"待审文案至少需要 {min_len} 个字符", {"length": len(cleaned), "minLength": min_len})
    if len(cleaned) > max_len:
        raise IpError(422, "text_too_long", f"待审文案不能超过 {max_len} 个字符", {"length": len(cleaned), "maxLength": max_len})

    findings = []
    for rule in spec.get("rules", []):
        hits = _rule_hits(rule, cleaned)
        if hits:
            findings.append({
                "rule": rule["id"],
                "label": rule["label"],
                "severity": rule["severity"],
                "hits": hits,
                "fix": rule.get("fix", ""),
            })
    order = {"blocker": 0, "major": 1, "minor": 2}
    findings.sort(key=lambda item: order.get(item["severity"], 9))
    if any(item["severity"] == "blocker" for item in findings):
        verdict = "reject"
    elif findings:
        verdict = "revise"
    else:
        verdict = "pass"

    reviewed_at = _now()
    review_id = new_id("review")
    record = {
        "id": review_id,
        "at": reviewed_at,
        "module": MODULE_ID,
        "role": role,
        "actor": actor_label(role),
        "target": _single_line(target) or "未命名文案",
        "text": cleaned,
        "verdict": verdict,
        "verdictLabel": spec.get("verdicts", {}).get(verdict, verdict),
        "findings": findings,
        "counts": {
            "blockers": sum(1 for item in findings if item["severity"] == "blocker"),
            "majors": sum(1 for item in findings if item["severity"] == "major"),
            "minors": sum(1 for item in findings if item["severity"] == "minor"),
        },
    }
    store().put(COLL_REVIEWS, review_id, record)
    _log("review", review_id, f"内容审核 · {record['verdictLabel']}", role, record["target"], {"verdict": verdict})
    return {
        "verdict": verdict,
        "verdictLabel": record["verdictLabel"],
        "findings": findings,
        "reviewedAt": reviewed_at,
        "reviewId": review_id,
        "counts": record["counts"],
        "review": record,
    }


def reviews_payload(limit: int = 20) -> dict:
    cfg = config()
    rows = store().list(COLL_REVIEWS, limit)
    rows.reverse()
    counts = {"pass": 0, "revise": 0, "reject": 0}
    for row in rows:
        if row.get("verdict") in counts:
            counts[row["verdict"]] += 1
    return {
        "reviews": rows,
        "count": len(rows),
        "total": store().count(COLL_REVIEWS),
        "counts": counts,
        "verdicts": cfg["review"].get("verdicts", {}),
        "rules": cfg["review"].get("rules", []),
        "samples": cfg["review"].get("samples", {}),
    }


def _parse_term(value) -> int:
    if isinstance(value, bool):
        raise IpError(422, "term_invalid", "授权期限必须是月数")
    if isinstance(value, int):
        term = value
    else:
        match = re.search(r"\d+", str(value or ""))
        if not match:
            raise IpError(422, "term_invalid", "授权期限必须包含月数，如 12")
        term = int(match.group(0))
    if not 1 <= term <= 60:
        raise IpError(422, "term_invalid", "授权期限需在 1–60 个月之间", {"term": term})
    return term


def license_preview(data: dict, role: str = "admin") -> dict:
    _require_role(role, "license.preview")
    cfg = config()
    spec = cfg["license"]
    licensee = _single_line(data.get("licensee"), 60)
    if len(licensee) < 2:
        raise IpError(422, "licensee_invalid", "被许可方名称至少 2 个字符")
    purpose = _single_line(data.get("purpose"), 40)
    if purpose not in spec.get("purposes", []):
        raise IpError(422, "purpose_invalid", "授权用途不在可授权清单内", {"allowed": spec.get("purposes", [])})
    territory = _single_line(data.get("territory"), 40)
    if territory not in spec.get("territories", []):
        raise IpError(422, "territory_invalid", "授权区域不在可授权清单内", {"allowed": spec.get("territories", [])})
    term_months = _parse_term(data.get("term"))
    base_fee = int(spec.get("baseFeeCents", 0))
    royalty_bps = int(spec.get("derivativeRoyaltyBps", 0))
    generated_at = _now()
    draft_no = f"IP-LIC-{datetime.now():%Y%m%d}-{new_id('d').split('-')[1].upper()}"
    values = {
        "licensee": licensee,
        "purpose": purpose,
        "territory": territory,
        "termMonths": term_months,
        "baseFee": f"{base_fee / 100:,.2f} 元",
        "royalty": f"{royalty_bps / 100:g}%",
    }
    clauses = []
    for clause in spec.get("clauses", []):
        try:
            body = str(clause["text"]).format(**values)
        except (KeyError, ValueError):
            body = str(clause["text"])
        clauses.append({"no": clause["no"], "title": clause["title"], "text": body})
    header = (
        f"《{cfg['story']['title']}》文化 IP 授权合同（草稿）\n"
        f"合同编号：{draft_no}\n"
        f"模板版本：{spec.get('templateVersion', 'IP-LIC-TPL-1.0')}\n"
        f"生成时间：{generated_at}\n\n"
        f"特别声明：{spec.get('disclaimer', '')}\n\n"
        f"授权摘要：被许可方 {licensee}；用途 {purpose}；区域 {territory}；期限 {term_months} 个月。\n"
    )
    body_text = "\n".join(f"第{clause['no']}条 {clause['title']}\n{clause['text']}" for clause in clauses)
    full_text = header + "\n" + body_text + "\n\n（本文件为产品演示模板，不构成法律意见，不产生真实授权效力。）"
    license_id = new_id("lic")
    draft = {
        "id": license_id,
        "draftNo": draft_no,
        "templateVersion": spec.get("templateVersion"),
        "generatedAt": generated_at,
        "licensee": licensee,
        "purpose": purpose,
        "territory": territory,
        "termMonths": term_months,
        "baseFeeCents": base_fee,
        "baseFee": values["baseFee"],
        "derivativeRoyaltyBps": royalty_bps,
        "derivativeRoyalty": values["royalty"],
        "clauses": clauses,
        "clauseCount": len(clauses),
        "disclaimer": spec.get("disclaimer", ""),
        "notice": "模板样例，不构成法律意见",
        "fullText": full_text,
        "status": "draft",
        "statusLabel": "草稿 / 待律师审核",
        "role": role,
        "actor": actor_label(role),
    }
    store().put(COLL_LICENSES, license_id, draft)
    _log("license_preview", license_id, f"授权草稿 · {licensee}", role, purpose)
    return draft


def licenses_payload(limit: int = 10) -> dict:
    rows = store().list(COLL_LICENSES, limit)
    rows.reverse()
    summaries = []
    for row in rows:
        summaries.append({
            "id": row.get("id"),
            "draftNo": row.get("draftNo"),
            "licensee": row.get("licensee"),
            "purpose": row.get("purpose"),
            "territory": row.get("territory"),
            "termMonths": row.get("termMonths"),
            "generatedAt": row.get("generatedAt"),
            "clauseCount": row.get("clauseCount"),
        })
    return {"licenses": summaries, "count": len(summaries), "total": store().count(COLL_LICENSES)}


def derivatives_payload() -> dict:
    cfg = config()
    derivatives = cfg["derivatives"]
    return {
        "derivatives": derivatives,
        "skus": derivatives.get("skus", []),
        "count": len(derivatives.get("skus", [])),
        "notes": derivatives.get("notes", ""),
        "disclaimer": "SKU 规格为合成样例，不代表真实供应商、报价或已上市商品。",
        "statusLabels": {"draft": "待授权"},
    }


def validate_assets(role: str = "admin", simulate_missing_audio: bool = False) -> dict:
    _require_role(role, "asset.validate")
    cfg = config()
    catalog = asset_catalog(simulate_missing_audio=simulate_missing_audio)
    summary = catalog["summary"]
    if catalog["missing"]:
        missing = [item["path"] for item in catalog["missing"]]
        raise IpError(
            422,
            "asset_missing",
            f"素材缺失：{', '.join(missing[:4])}" + (" 等" if len(missing) > 4 else ""),
            {
                "missing": missing,
                "missingCount": len(missing),
                "simulated": simulate_missing_audio,
                "checks": catalog["checks"],
            },
        )
    bad = [check for check in catalog["checks"] if not check["ok"]]
    if bad:
        raise IpError(422, "asset_invalid", "素材校验未通过：" + "；".join(item["label"] for item in bad),
                      {"checks": catalog["checks"], "warnings": bad})
    report = duration_report(cfg)
    master_meta = wav_meta(ROOT / cfg["media"]["masterAudio"].lstrip("/"))
    tolerance = int(cfg["media"].get("durationToleranceMs", 120))
    if not master_meta or abs(master_meta["durationMs"] - report["totalMs"]) > tolerance:
        raise IpError(422, "master_duration_mismatch", "总配音时长与分镜时间轴不一致",
                      {"master": master_meta, "timelineMs": report["totalMs"]})
    return {
        "ok": True,
        "summary": summary,
        "checks": catalog["checks"],
        "timelineMs": report["totalMs"],
        "masterAudioMs": master_meta["durationMs"],
        "simulated": simulate_missing_audio,
    }


def reset_demo() -> dict:
    before = {
        "reviews": store().count(COLL_REVIEWS),
        "licenses": store().count(COLL_LICENSES),
        "events": store().count(COLL_EVENTS),
    }
    store().reset()
    return {"cleared": before, "total": sum(before.values()), "mediaUntouched": True}


def dashboard() -> dict:
    cfg = config()
    report = duration_report(cfg)
    catalog = asset_catalog()
    manifest = build_manifest()
    reviews = store().list(COLL_REVIEWS, 500)
    licenses = store().list(COLL_LICENSES, 500)
    counts = {"pass": 0, "revise": 0, "reject": 0}
    for review in reviews:
        if review.get("verdict") in counts:
            counts[review["verdict"]] += 1
    last_review = reviews[-1] if reviews else None
    last_license = licenses[-1] if licenses else None
    ready = bool(report["ok"] and catalog["summary"]["missing"] == 0 and manifest["assetsOk"])
    return {
        "module": MODULE_ID,
        "characters": len(cfg["characters"]),
        "beats": len(cfg["story"].get("beats", [])),
        "shots": len(cfg["shots"]),
        "skus": len(cfg["derivatives"].get("skus", [])),
        "reviewRules": len(cfg["review"].get("rules", [])),
        "totalMs": report["totalMs"],
        "totalSeconds": report["totalSeconds"],
        "durationOk": report["ok"],
        "duration": report,
        "assets": catalog["summary"],
        "voiceClips": catalog["summary"]["voices"],
        "masterAudioMs": manifest["master"].get("durationMs"),
        "audioTotalMs": manifest["audioTotalMs"],
        "allAudioFits": manifest["allAudioFits"],
        "reviews": {"total": len(reviews), **counts},
        "licenses": len(licenses),
        "lastReviewAt": (last_review or {}).get("at"),
        "lastReviewVerdict": (last_review or {}).get("verdict"),
        "lastLicenseAt": (last_license or {}).get("generatedAt"),
        "lastLicenseNo": (last_license or {}).get("draftNo"),
        "ready": ready,
        "mediaWarnings": manifest["warnings"],
        "voiceName": cfg["media"]["voiceName"],
    }


def _config_payload() -> dict:
    cfg = config()
    report = duration_report(cfg)
    permissions = []
    for capability, roles in cfg.get("permissions", {}).items():
        permissions.append({
            "capability": capability,
            "label": capability_label(capability),
            "roles": [{"role": role, "label": actor_label(role)} for role in roles],
        })
    return {
        "module": {
            "id": MODULE_ID,
            "key": cfg["module"].get("key", "C"),
            "name": cfg["module"].get("name", MODULE_NAME),
            "version": cfg["module"].get("version", "1.0.0"),
            "title": cfg["module"].get("title"),
            "subtitle": cfg["module"].get("subtitle"),
            "logline": cfg["module"].get("logline"),
            "synopsis": cfg["module"].get("synopsis"),
            "disclaimer": cfg["module"].get("disclaimer"),
            "engineNote": cfg["module"].get("engineNote"),
        },
        "sampleData": bool(cfg.get("sampleData", True)),
        "characters": cfg["characters"],
        "story": {
            "title": cfg["story"].get("title"),
            "format": cfg["story"].get("format"),
            "beats": cfg["story"].get("beats", []),
            "scriptNotes": cfg["story"].get("scriptNotes", []),
        },
        "media": {
            "voiceName": cfg["media"]["voiceName"],
            "voiceFormat": cfg["media"].get("voiceFormat"),
            "masterAudio": cfg["media"]["masterAudio"],
            "masterSrt": cfg["media"]["masterSrt"],
            "minMs": cfg["media"]["minMs"],
            "maxMs": cfg["media"]["maxMs"],
            "totalMs": report["totalMs"],
            "totalSeconds": report["totalSeconds"],
            "durationOk": report["ok"],
            "shotCount": len(cfg["shots"]),
            "style": cfg["media"].get("style"),
        },
        "counts": {
            "characters": len(cfg["characters"]),
            "beats": len(cfg["story"].get("beats", [])),
            "shots": len(cfg["shots"]),
            "reviewRules": len(cfg["review"].get("rules", [])),
            "licenseClauses": len(cfg["license"].get("clauses", [])),
            "skus": len(cfg["derivatives"].get("skus", [])),
        },
        "duration": report,
        "review": {
            "minTextLength": cfg["review"]["minTextLength"],
            "maxTextLength": cfg["review"]["maxTextLength"],
            "verdicts": cfg["review"].get("verdicts", {}),
            "samples": cfg["review"].get("samples", {}),
            "rules": cfg["review"].get("rules", []),
        },
        "license": {
            **{key: value for key, value in cfg["license"].items() if key != "clauses"},
            "clauses": cfg["license"].get("clauses", []),
            "clauseCount": len(cfg["license"].get("clauses", [])),
        },
        "derivatives": {
            "notes": cfg["derivatives"].get("notes"),
            "skus": cfg["derivatives"].get("skus", []),
            "count": len(cfg["derivatives"].get("skus", [])),
        },
        "permissions": permissions,
        "permissionMap": cfg.get("permissions", {}),
        "capabilityLabels": {cap: capability_label(cap) for cap in cfg.get("permissions", {})},
        "actors": cfg.get("actors", {}),
        "statusLabels": {
            "review": cfg["review"].get("verdicts", {}),
            "license": {"draft": "草稿 / 待律师审核"},
            "sku": {"draft": "待授权"},
        },
    }


def _scenario_step(title: str, fn, *, expect_error: bool = False) -> dict:
    try:
        result = fn()
        if expect_error:
            return {
                "title": title,
                "ok": True,
                "expectError": True,
                "unexpected": True,
                "message": "预期失败，但调用成功",
                "result": result,
            }
        return {"title": title, "ok": True, "expectError": False, "result": result}
    except IpError as exc:
        payload = {
            "title": title,
            "ok": False,
            "expectError": bool(expect_error),
            "status": exc.status,
            "error": exc.error,
            "message": exc.message,
            "extra": exc.extra,
        }
        if expect_error:
            payload["satisfied"] = True
        return payload
    except Exception as exc:  # scenario keeps going and reports the failure honestly
        traceback.print_exc()
        return {
            "title": title,
            "ok": False,
            "expectError": bool(expect_error),
            "status": 500,
            "error": "internal_error",
            "message": f"{type(exc).__name__}: {exc}",
            "extra": {},
        }


def run_scenario(role: str = "admin") -> dict:
    reset_demo()
    cfg = config()
    steps: list[dict] = []

    def s_config():
        cfg_now = config()
        if len(cfg_now["characters"]) != 2 or len(cfg_now["shots"]) < 10:
            raise IpError(422, "config_invalid", "角色或分镜数量不满足要求")
        return {
            "module": cfg_now["module"].get("name"),
            "version": cfg_now["module"].get("version"),
            "characters": [c["name"] for c in cfg_now["characters"]],
            "shots": len(cfg_now["shots"]),
            "beats": len(cfg_now["story"].get("beats", [])),
            "reviewRules": len(cfg_now["review"].get("rules", [])),
            "licenseClauses": len(cfg_now["license"].get("clauses", [])),
            "skus": len(cfg_now["derivatives"].get("skus", [])),
        }

    def s_characters():
        chars = config()["characters"]
        required = ("name", "role", "setting", "motifs", "personality", "voice", "can", "cannot", "portrait")
        for char in chars:
            missing = [key for key in required if not char.get(key)]
            if missing:
                raise IpError(422, "character_incomplete", f"{char.get('name', '?')} 缺少 {', '.join(missing)}")
        return {
            "characters": [{"name": c["name"], "role": c["role"], "motifs": c["motifs"], "voice": c["voice"]["profile"]} for c in chars],
            "canCounts": [len(c["can"]) for c in chars],
            "cannotCounts": [len(c["cannot"]) for c in chars],
        }

    def s_beats():
        beats = config()["story"].get("beats", [])
        covered = sorted(no for beat in beats for no in beat.get("shots", []))
        expected = list(range(1, len(config()["shots"]) + 1))
        if covered != expected:
            raise IpError(422, "beat_coverage_invalid", "剧本节拍未完整覆盖分镜")
        return {"beats": len(beats), "coverage": covered, "titles": [beat["title"] for beat in beats]}

    def s_shots():
        data = story_payload()
        if data["fieldIssues"]:
            raise IpError(422, "shot_incomplete", "分镜字段不完整", {"issues": data["fieldIssues"]})
        first = data["shots"][0]
        return {
            "shots": len(data["shots"]),
            "fieldsPerShot": len(data["shotFields"]),
            "first": {"no": first["no"], "scene": first["scene"], "durationMs": first["durationMs"], "caption": first["caption"]},
            "speakers": sorted({shot["speaker"] for shot in data["shots"]}),
        }

    def s_duration():
        report = duration_report()
        if not report["ok"]:
            raise IpError(422, "duration_invalid", "分镜总时长不在 30–45 秒内", {"duration": report})
        return report

    def s_assets():
        catalog = asset_catalog()
        if catalog["summary"]["missing"]:
            raise IpError(422, "asset_missing", "存在缺失素材", {"missing": [item["path"] for item in catalog["missing"]]})
        return {"summary": catalog["summary"], "checks": catalog["checks"]}

    def s_manifest():
        manifest = build_manifest()
        expected = 0
        for shot in manifest["shots"]:
            if shot["startMs"] != expected:
                raise IpError(422, "timeline_gap", f"分镜 {shot['index']} 时间轴不连续")
            expected = shot["endMs"]
        if not (manifest["minMs"] <= manifest["totalMs"] <= manifest["maxMs"]):
            raise IpError(422, "manifest_duration_invalid", "manifest 总时长不在 30–45 秒内")
        return {
            "totalMs": manifest["totalMs"],
            "totalSeconds": manifest["totalSeconds"],
            "shots": manifest["shotCount"],
            "masterMs": manifest["master"].get("durationMs"),
            "masterSrtCues": manifest["master"].get("srtCues"),
            "contiguous": True,
            "audioTotalMs": manifest["audioTotalMs"],
            "allAudioFits": manifest["allAudioFits"],
        }

    def s_voice():
        manifest = build_manifest()
        clips = [{"no": shot["index"], "durationMs": shot["audioDurationMs"], "sampleRate": shot["audioSampleRate"], "fits": shot["audioFitsSlot"]} for shot in manifest["shots"]]
        rates = sorted({clip["sampleRate"] for clip in clips if clip["sampleRate"]})
        if rates != [22050]:
            raise IpError(422, "voice_format_invalid", f"配音采样率异常：{rates}")
        if not all(clip["fits"] for clip in clips):
            raise IpError(422, "voice_overflow", "存在配音超出分镜时长的片段")
        return {
            "clips": len(clips),
            "sampleRates": rates,
            "totalAudioMs": sum(clip["durationMs"] or 0 for clip in clips),
            "minMs": min(clip["durationMs"] or 0 for clip in clips),
            "maxMs": max(clip["durationMs"] or 0 for clip in clips),
            "detail": clips,
        }

    def s_subtitles():
        cfg_now = config()
        cues = []
        missing = []
        for shot in cfg_now["shots"]:
            meta = srt_meta(ROOT / shot["srt"].lstrip("/"))
            if not meta:
                missing.append(shot["srt"])
            else:
                cues.append(meta["cues"])
        master = srt_meta(ROOT / cfg_now["media"]["masterSrt"].lstrip("/"))
        if missing or not master:
            raise IpError(422, "subtitle_missing", "字幕文件缺失", {"missing": missing})
        if master["cues"] != len(cfg_now["shots"]):
            raise IpError(422, "subtitle_invalid", f"总字幕应为 {len(cfg_now['shots'])} 条，实际 {master['cues']} 条")
        return {
            "masterCues": master["cues"],
            "shotSrt": len(cues),
            "firstCue": master["firstCue"],
            "masterBytes": master["bytes"],
        }

    def s_review_pass():
        sample = config()["review"]["samples"]["pass"]
        result = review_text(sample, "合规样片宣传文案", "ops")
        if result["verdict"] != "pass":
            raise IpError(422, "review_expected_pass", f"合规文案未通过：{result['verdict']}", {"findings": result["findings"]})
        return {"reviewId": result["reviewId"], "verdict": result["verdict"], "findings": len(result["findings"]), "reviewedAt": result["reviewedAt"]}

    def s_review_reject():
        sample = config()["review"]["samples"]["reject"]
        result = review_text(sample, "违规示例文案", "ops")
        if result["verdict"] != "reject":
            raise IpError(422, "review_expected_reject", f"违规文案未拒绝：{result['verdict']}")
        return {
            "reviewId": result["reviewId"],
            "verdict": result["verdict"],
            "findings": len(result["findings"]),
            "rules": [item["rule"] for item in result["findings"]],
            "labels": [item["label"] for item in result["findings"]],
        }

    def s_review_log():
        rows = store().list(COLL_REVIEWS, 20)
        if len(rows) < 2:
            raise IpError(422, "review_log_missing", "审核留痕少于 2 条")
        return {"count": len(rows), "verdicts": [row["verdict"] for row in rows], "ids": [row["id"] for row in rows]}

    def s_license():
        draft = license_preview({
            "licensee": "合成样例文化品牌（演示）",
            "purpose": "品牌短片",
            "territory": "中国大陆",
            "term": 12,
        }, "finance")
        if len(draft["clauses"]) < 10:
            raise IpError(422, "license_incomplete", "授权条款少于 10 条")
        return {
            "licenseId": draft["id"],
            "draftNo": draft["draftNo"],
            "licensee": draft["licensee"],
            "purpose": draft["purpose"],
            "territory": draft["territory"],
            "termMonths": draft["termMonths"],
            "clauses": draft["clauseCount"],
            "baseFee": draft["baseFee"],
            "disclaimer": draft["disclaimer"],
        }

    def s_derivatives():
        data = derivatives_payload()
        if data["count"] < 5:
            raise IpError(422, "sku_incomplete", "衍生品 SKU 少于 5 个")
        bad = [sku["id"] for sku in data["skus"] if not sku.get("specs") or not sku.get("royaltyBps")]
        if bad:
            raise IpError(422, "sku_invalid", f"SKU 规格或分成缺失：{bad}")
        return {"count": data["count"], "skus": [{"id": sku["id"], "name": sku["name"], "category": sku["category"], "moq": sku["moq"]} for sku in data["skus"]]}

    def s_forbidden():
        review_text("这是一条越权审核测试文案。", "越权测试", "workshop")

    def s_missing_audio():
        validate_assets(role="admin", simulate_missing_audio=True)

    steps.append(_scenario_step("加载模块配置（双角色 / 12 格分镜 / 9 条审核规则）", s_config))
    steps.append(_scenario_step("角色手册：远视/远听设定、母题、声音画像、能与不能", s_characters))
    steps.append(_scenario_step("剧本节拍：6 场覆盖 12 格分镜", s_beats))
    steps.append(_scenario_step("分镜表：逐格字段完整并含字幕台词", s_shots))
    steps.append(_scenario_step("时长校验：总时长落在 30–45 秒", s_duration))
    steps.append(_scenario_step("素材清单：SVG / WAV / SRT 全部存在", s_assets))
    steps.append(_scenario_step("播放器 manifest：时间轴连续、总时长合规", s_manifest))
    steps.append(_scenario_step("真实配音：12 段 WAV 均为 22.05kHz 且不超镜长", s_voice))
    steps.append(_scenario_step("字幕：12 段分镜 SRT + 12 条总字幕", s_subtitles))
    steps.append(_scenario_step("内容审核：合规文案通过并留痕", s_review_pass))
    steps.append(_scenario_step("内容审核：违规文案被拒绝并命中规则", s_review_reject))
    steps.append(_scenario_step("审核留痕：两次审核记录可查询", s_review_log))
    steps.append(_scenario_step("授权草稿：12 条条款与免责声明", s_license))
    steps.append(_scenario_step("衍生品：6 个 SKU 规格与分成", s_derivatives))
    steps.append(_scenario_step("越权被拒：工坊角色不能执行内容审核", s_forbidden, expect_error=True))
    steps.append(_scenario_step("缺失 wav 报错：故障注入 shot-01.wav 被校验拦截", s_missing_audio, expect_error=True))

    ok_count = sum(1 for step in steps if step["ok"] and not step.get("expectError"))
    expected_count = sum(1 for step in steps if step.get("expectError") and not step["ok"])
    satisfied = sum(1 for step in steps if (step["ok"] and not step.get("unexpected")) or step.get("satisfied"))
    unexpected = sum(1 for step in steps if step.get("unexpected"))
    summary = {
        "steps": len(steps),
        "passed": satisfied,
        "expectedFailures": expected_count,
        "okSteps": ok_count,
        "unexpected": unexpected,
        "failed": len(steps) - satisfied,
        "durationOk": duration_report(cfg)["ok"],
        "reviewPass": steps[9].get("result", {}).get("verdict") if steps[9].get("ok") else None,
        "reviewReject": steps[10].get("result", {}).get("verdict") if steps[10].get("ok") else None,
        "licenseNo": steps[12].get("result", {}).get("draftNo") if steps[12].get("ok") else None,
    }
    return {
        "ok": True,
        "scenario": SCENARIO_NAME,
        "generatedAt": _now(),
        "steps": steps,
        "summary": summary,
        "dashboard": dashboard(),
    }


def _route_get(handler, path: str) -> None:
    clean = path.rstrip("/") or "/api/ip"
    if clean == "/api/ip/config":
        _send(handler, 200, {"ok": True, **_config_payload()})
        return
    if clean == "/api/ip/characters":
        _send(handler, 200, {"ok": True, **characters_payload()})
        return
    if clean == "/api/ip/story":
        _send(handler, 200, {"ok": True, **story_payload()})
        return
    if clean == "/api/ip/assets":
        catalog = asset_catalog()
        _send(handler, 200, {"ok": True, **catalog})
        return
    if clean == "/api/ip/media-manifest":
        manifest = build_manifest()
        _send(handler, 200, {"ok": True, **manifest})
        return
    if clean == "/api/ip/reviews":
        limit = _query_int(handler, "limit", 20, 1, 100)
        _send(handler, 200, {"ok": True, **reviews_payload(limit)})
        return
    if clean == "/api/ip/derivatives":
        _send(handler, 200, {"ok": True, **derivatives_payload()})
        return
    if clean == "/api/ip/licenses":
        limit = _query_int(handler, "limit", 10, 1, 50)
        _send(handler, 200, {"ok": True, **licenses_payload(limit)})
        return
    if clean == "/api/ip/dashboard":
        _send(handler, 200, {"ok": True, "dashboard": dashboard()})
        return
    raise IpError(404, "not_found", f"未找到接口 {path}")


def _route_post(handler, path: str) -> None:
    clean = path.rstrip("/")
    payload = _read_json(handler)
    role = _single_line(payload.get("role"), 30) or "admin"
    if clean == "/api/ip/review":
        result = review_text(payload.get("text"), payload.get("target"), role)
        _send(handler, 200, {"ok": True, **result})
        return
    if clean == "/api/ip/license/preview":
        draft = license_preview(payload, role)
        _send(handler, 200, {"ok": True, "license": draft, "notice": draft["notice"]})
        return
    if clean == "/api/ip/assets/validate":
        result = validate_assets(role=role)
        _send(handler, 200, {"ok": True, **result})
        return
    if clean == "/api/ip/scenario":
        _send(handler, 200, run_scenario(role))
        return
    if clean == "/api/ip/demo/reset":
        _require_role(role, "demo.reset")
        result = reset_demo()
        _send(handler, 200, {"ok": True, **result})
        return
    raise IpError(404, "not_found", f"未找到接口 {path}")


def _handle(handler, method: str, path: str) -> bool:
    if not path.startswith("/api/ip/"):
        return False
    try:
        if method == "GET":
            _route_get(handler, path)
        elif method == "POST":
            _route_post(handler, path)
        else:
            raise IpError(405, "method_not_allowed", "仅支持 GET / POST")
    except IpError as exc:
        body = {"ok": False, "error": exc.error, "message": exc.message}
        body.update(exc.extra)
        _send(handler, exc.status, body)
    except ValueError as exc:
        _send(handler, 400, {"ok": False, "error": "invalid_request", "message": str(exc)})
    except Exception:
        traceback.print_exc()
        _send(handler, 500, {"ok": False, "error": "internal_error", "message": "IP 模块内部错误"})
    return True


def handle_get(handler, path: str) -> bool:
    return _handle(handler, "GET", path)


def handle_post(handler, path: str) -> bool:
    return _handle(handler, "POST", path)
