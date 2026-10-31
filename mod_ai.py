"""B · 六产业共享企业 AI 服务层（珠宝 / 木作）本地规则引擎。

设计边界（如实声明）：
- 检索为确定性的关键词 + 字符 n-gram 打分，不调用外部模型 / API；
- 智能体为本地意图路由，只做检索引用、询盘建线索、工作流草稿三类动作；
- 通知只写站内模拟记录，不发邮件 / 短信；报价草稿必须人工复核。

数据文件：config/ai_industries.json、config/ai_engine.json、config/ai_handbook.json
存储：data/ai.db（JsonStore，命名空间 ai），与 m2.db 隔离。
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from jsonstore import JsonStore, new_id

ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
ENGINE_PATH = CONFIG_DIR / "ai_engine.json"
INDUSTRIES_PATH = CONFIG_DIR / "ai_industries.json"
HANDBOOK_PATH = CONFIG_DIR / "ai_handbook.json"

_CONFIG_CACHE: dict[str, tuple[int, Any]] = {}
_CACHE_LOCK = threading.RLock()
_STORE_LOCK = threading.RLock()
_STORE: JsonStore | None = None
_STORE_OVERRIDE: Path | None = None

STOP_EN = {
    "the", "and", "for", "with", "that", "this", "from", "your", "you", "are", "was",
    "were", "have", "has", "had", "not", "but", "our", "their", "its", "can", "will",
    "would", "should", "about", "into", "than", "then", "them", "they", "use", "using",
}
STOP_BG = {
    "我们", "你们", "他们", "可以", "需要", "以及", "如果", "因为", "所以", "这个",
    "那个", "进行", "一个", "已经", "并且", "或者", "但是", "没有", "不是", "就是",
    "什么", "怎么", "如何", "是否", "多少", "哪些", "时候", "还是", "可能", "应该",
}


class AIError(Exception):
    """可映射为 HTTP 4xx 的业务错误。"""

    def __init__(self, status: int, error: str, message: str, extra: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.error = error
        self.message = message
        self.extra = extra or {}


# --------------------------------------------------------------------------- #
# 基础工具 / 配置 / 存储
# --------------------------------------------------------------------------- #
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_json(path: Path) -> Any:
    st = path.stat()
    key = str(path)
    with _CACHE_LOCK:
        cached = _CONFIG_CACHE.get(key)
        if cached and cached[0] == st.st_mtime_ns:
            return cached[1]
    data = json.loads(path.read_text(encoding="utf-8"))
    with _CACHE_LOCK:
        _CONFIG_CACHE[key] = (st.st_mtime_ns, data)
    return data


def engine_config() -> dict[str, Any]:
    return _load_json(ENGINE_PATH)


def industries_config() -> dict[str, Any]:
    return _load_json(INDUSTRIES_PATH)


def handbook_config() -> dict[str, Any]:
    return _load_json(HANDBOOK_PATH)


def set_store_path(path: str | Path | None = None) -> None:
    """测试 / 独立实例用：切换数据库路径并清空缓存句柄。"""

    global _STORE, _STORE_OVERRIDE
    with _STORE_LOCK:
        _STORE_OVERRIDE = Path(path) if path else None
        _STORE = None


def store() -> JsonStore:
    global _STORE
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                env_path = os.environ.get("CRAFTMESH_AI_DB") or ""
                path = Path(env_path) if env_path else DATA_DIR / "ai.db"
                if _STORE_OVERRIDE is not None:
                    path = _STORE_OVERRIDE
                _STORE = JsonStore(path, "ai")
    return _STORE


def _industry(industry_id: str) -> dict[str, Any]:
    cfg = industries_config()
    industry = cfg.get("industries", {}).get(industry_id)
    if not industry:
        raise AIError(422, "invalid_industry", f"未知行业：{industry_id}（可选 jewelry / woodcraft）", {
            "industries": list(cfg.get("industries", {}).keys())
        })
    return industry


def current_industry() -> str:
    cfg = industries_config()
    default = cfg.get("defaultIndustry", "jewelry")
    row = store().get("settings", "current") or {}
    industry = str(row.get("industry") or default)
    if industry not in cfg.get("industries", {}):
        industry = default
    return industry


def _languages() -> dict[str, str]:
    """兼容 engine.languages 列表与旧版字典两种配置形状。"""

    eng = engine_config()
    raw = eng.get("engine", {}).get("languages") or eng.get("languages") or ["zh", "en", "ja"]
    labels = eng.get("engine", {}).get("languageLabels") or {}
    if isinstance(raw, dict):
        return {str(key): str(value) for key, value in raw.items()}
    return {str(code): str(labels.get(code, code)) for code in raw}


def _role_label(role: str) -> str:
    return engine_config().get("roles", {}).get(role, role)


def _check_role(role: str | None, action: str) -> str:
    eng = engine_config()
    role = str(role or "admin").strip() or "admin"
    if role not in eng.get("roles", {}):
        raise AIError(403, "forbidden", f"未知角色：{role}", {"role": role})
    allowed = eng.get("permissions", {}).get(action, [])
    if role not in allowed:
        label = eng.get("actionLabels", {}).get(action, action)
        raise AIError(403, "forbidden", f"角色 {role} 不能执行「{label}」", {
            "role": role, "action": action, "allowed": allowed,
        })
    return role


def _log_event(action: str, role: str, target: str, ok: bool = True, detail: str = "") -> None:
    event_id = new_id("evt")
    store().put("events", event_id, {
        "id": event_id, "at": _now(), "action": action,
        "actionLabel": engine_config().get("actionLabels", {}).get(action, action),
        "role": role, "target": target, "ok": ok, "detail": detail,
    })


def _query(handler) -> dict[str, str]:
    raw = getattr(handler, "path", "") or ""
    values = parse_qs(urlparse(raw).query)
    return {key: val[-1] for key, val in values.items()}


def _read_json(handler) -> dict[str, Any]:
    raw_length = handler.headers.get("Content-Length")
    try:
        length = int(raw_length or 0)
    except (TypeError, ValueError):
        raise AIError(400, "invalid_request", "Content-Length 不合法")
    if length < 0:
        raise AIError(400, "invalid_request", "Content-Length 不合法")
    if length > 1_048_576:
        raise AIError(413, "payload_too_large", "请求体超过 1MB")
    raw = handler.rfile.read(length) if length else b""
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise AIError(400, "invalid_json", "请求体不是合法 JSON")
    if not isinstance(payload, dict):
        raise AIError(400, "invalid_request", "请求体必须是 JSON 对象")
    return payload


def _send(handler, status: int, payload: dict[str, Any]) -> None:
    handler._send_json(status, payload)


def _industry_brief(industry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": industry["id"],
        "name": industry["name"],
        "nameEn": industry.get("nameEn", ""),
        "tagline": industry.get("tagline", ""),
        "summary": industry.get("summary", ""),
    }


def _industry_counts(industry_id: str) -> dict[str, int]:
    docs = [d for d in store().list("docs", 1000) if d.get("industry") == industry_id]
    return {
        "documents": len(docs),
        "published": len([d for d in docs if d.get("status") == "published"]),
        "chunks": sum(len(d.get("chunks", [])) for d in docs),
    }


def _seed_docs() -> None:
    """幂等补齐两个行业的基线知识库；不覆盖用户改动过的同 ID 文档。"""

    cfg = industries_config()
    st = store()
    existing = {d["id"] for d in st.list("docs", 1000)}
    for industry in cfg.get("industries", {}).values():
        for doc in industry.get("knowledgeDocs", []):
            if doc["id"] in existing:
                continue
            chunks = []
            for index, item in enumerate(doc.get("chunks", []), start=1):
                chunks.append({
                    "id": f"c{index}",
                    "index": index,
                    "text": item["text"],
                    "keywords": list(item.get("keywords", [])),
                })
            record = {
                "id": doc["id"],
                "title": doc["title"],
                "industry": industry["id"],
                "version": doc.get("version", "v1.0"),
                "status": doc.get("status", "published"),
                "source": doc.get("source", "配置种子（合成样例）"),
                "owner": doc.get("owner", "未指定"),
                "updatedAt": doc.get("updatedAt", _now()[:10]),
                "createdAt": doc.get("updatedAt", _now()[:10]),
                "createdBy": "seed",
                "content": "\n\n".join(c["text"] for c in chunks),
                "chunkCount": len(chunks),
                "chunks": chunks,
                "keywords": _doc_keywords(chunks),
                "seed": True,
                "autoChunked": False,
            }
            st.put("docs", doc["id"], record)
            existing.add(doc["id"])
    if st.get("settings", "current") is None:
        st.put("settings", "current", {
            "industry": cfg.get("defaultIndustry", "jewelry"),
            "updatedAt": _now(),
        })


def ensure_seed() -> None:
    _seed_docs()


def _doc_keywords(chunks: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for chunk in chunks:
        for kw in chunk.get("keywords", []):
            if kw not in out:
                out.append(kw)
    return out[:24]


def _squash(text: str) -> str:
    return re.sub(r"[^0-9a-z\u3040-\u30ff\u4e00-\u9fff]+", "", str(text).lower())


def _query_terms(query: str) -> tuple[list[str], list[str], list[str], list[str]]:
    low = query.lower()
    words = list(dict.fromkeys(re.findall(r"[a-z0-9][a-z0-9._+-]*", low)))
    runs = list(dict.fromkeys(re.findall(r"[\u3040-\u30ff\u4e00-\u9fff]{2,}", low)))
    bigrams: list[str] = []
    trigrams: list[str] = []
    for run in runs:
        if len(run) == 2:
            bigrams.append(run)
        for i in range(max(0, len(run) - 1)):
            bigrams.append(run[i:i + 2])
        for i in range(max(0, len(run) - 2)):
            trigrams.append(run[i:i + 3])
    bigrams = list(dict.fromkeys(bigrams))[:16]
    trigrams = list(dict.fromkeys(trigrams))[:10]
    return words, runs, bigrams, trigrams


def _glossary_terms(industry: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for row in industry.get("glossary", []):
        for key in ("zh", "en", "ja"):
            value = str(row.get(key) or "").strip().lower()
            if value and value not in terms:
                terms.append(value)
    return terms


def _score_chunk(query: str, doc: dict[str, Any], chunk: dict[str, Any], industry: dict[str, Any]) -> int:
    weights = engine_config().get("search", {}).get("weights", {})
    q_low = query.lower()
    q_squash = _squash(query)
    text = f"{doc.get('title', '')}\n{chunk.get('text', '')}"
    low = text.lower()
    squashed = _squash(text)
    score = 0
    if len(q_squash) >= 2 and q_squash in squashed:
        score += int(weights.get("phrase", 8))
    words, runs, bigrams, trigrams = _query_terms(query)
    for keyword in chunk.get("keywords", []):
        kw = _squash(keyword)
        if len(kw) >= 2 and (kw in q_squash or (len(kw) >= 3 and q_squash in kw)):
            score += int(weights.get("keyword", 6))
    for run in runs:
        if run in low:
            score += 3
    for word in words:
        if len(word) >= 3 and word in low:
            score += 3
    for bigram in bigrams:
        if bigram in low:
            score += int(weights.get("bigram", 2))
    for trigram in trigrams:
        if trigram in low:
            score += int(weights.get("trigram", 1))
    title_low = doc.get("title", "").lower()
    for run in runs:
        if run in title_low:
            score += int(weights.get("title", 2))
    for term in _glossary_terms(industry):
        if term in q_low and _squash(term) in squashed:
            score += int(weights.get("glossary", 4))
    return score


def _public_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    return {"id": chunk["id"], "index": chunk["index"], "text": chunk["text"], "keywords": chunk.get("keywords", [])}


def _doc_public(doc: dict[str, Any], include_chunks: bool = False) -> dict[str, Any]:
    payload = {key: val for key, val in doc.items() if key != "chunks"}
    payload["chunkCount"] = len(doc.get("chunks", []))
    if include_chunks:
        payload["chunks"] = [_public_chunk(c) for c in doc.get("chunks", [])]
    return payload


def _doc_brief(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": doc["id"], "title": doc["title"], "industry": doc["industry"],
        "version": doc.get("version"), "status": doc.get("status"),
        "statusLabel": engine_config().get("statusLabels", {}).get("knowledge", {}).get(doc.get("status"), doc.get("status")),
        "source": doc.get("source"), "owner": doc.get("owner"),
        "chunkCount": len(doc.get("chunks", [])), "updatedAt": doc.get("updatedAt"),
        "keywords": doc.get("keywords", [])[:8],
    }


# --------------------------------------------------------------------------- #
# 知识库：切块 / 写入 / 检索
# --------------------------------------------------------------------------- #
def _auto_keywords(text: str, industry: dict[str, Any]) -> list[str]:
    low = text.lower()
    found: list[str] = []
    for row in industry.get("glossary", []):
        for key in ("zh", "en", "ja"):
            term = str(row.get(key) or "").strip()
            if term and term.lower() in low and term not in found:
                found.append(term)
    latin = [w for w in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{2,}", low) if w not in STOP_EN]
    freq: dict[str, int] = {}
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(run) < 2:
            continue
        for i in range(len(run) - 1):
            bg = run[i:i + 2]
            if bg in STOP_BG:
                continue
            freq[bg] = freq.get(bg, 0) + 1
    grams = [k for k, _ in sorted(freq.items(), key=lambda kv: (-kv[1], text.find(kv[0])))[:8]]
    out: list[str] = []
    for item in found + latin + grams:
        if item and item not in out:
            out.append(item)
    return out[:10]


def _chunk_content(content: str, industry: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = engine_config().get("chunking", {})
    max_chars = int(cfg.get("maxChars", 180))
    max_chunks = int(cfg.get("maxChunks", 60))
    units: list[str] = []
    for para in re.split(r"\n\s*\n", content):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            units.append(para)
            continue
        sentences = re.split(r"(?<=[。！？!?；;])", para)
        buf = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(buf) + len(sentence) <= max_chars:
                buf += sentence
                continue
            if buf:
                units.append(buf.strip())
            while len(sentence) > max_chars:
                units.append(sentence[:max_chars].strip())
                sentence = sentence[max_chars:]
            buf = sentence
        if buf.strip():
            units.append(buf.strip())
    units = [u for u in units if u]
    if not units:
        raise AIError(422, "empty_content", "文档内容切块后为空，请补充可检索的正文")
    if len(units) > max_chunks:
        raise AIError(422, "too_many_chunks", f"文档切块数 {len(units)} 超过上限 {max_chunks}，请拆分文档")
    return [
        {"id": f"c{index}", "index": index, "text": text, "keywords": _auto_keywords(text, industry)}
        for index, text in enumerate(units, start=1)
    ]


def write_knowledge(payload: dict[str, Any], role: str = "admin") -> dict[str, Any]:
    _check_role(role, "knowledge.write")
    ensure_seed()
    eng = engine_config()
    limits = eng.get("limits", {})
    status_labels = eng.get("statusLabels", {}).get("knowledge", {})

    doc_id = str(payload.get("id") or "").strip()
    existing = store().get("docs", doc_id) if doc_id else None
    if doc_id and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{2,60}", doc_id):
        raise AIError(422, "invalid_doc_id", "文档 ID 只能包含字母、数字、下划线和短横线（3–61 位）")

    industry_id = str(payload.get("industry") or (existing or {}).get("industry") or current_industry()).strip()
    industry = _industry(industry_id)
    title = str(payload.get("title") or (existing or {}).get("title") or "").strip()
    if not title:
        raise AIError(422, "missing_title", "文档标题不能为空")
    if len(title) > int(limits.get("titleMaxChars", 120)):
        raise AIError(422, "title_too_long", f"文档标题不能超过 {limits.get('titleMaxChars', 120)} 字")

    raw_content = payload.get("content")
    if raw_content is None or str(raw_content).strip() == "":
        content = str((existing or {}).get("content") or "").strip()
    else:
        content = str(raw_content).strip()
    if not content:
        raise AIError(422, "missing_content", "文档正文不能为空")
    max_content = int(limits.get("contentMaxChars", 12000))
    if len(content) > max_content:
        raise AIError(422, "content_too_long", f"文档正文超过 {max_content} 字上限，请拆分")
    if len(content) < 20:
        raise AIError(422, "content_too_short", "文档正文至少 20 字，过短内容无法形成有效检索块")

    status = str(payload.get("status") or (existing or {}).get("status") or "published").strip()
    if status not in status_labels:
        raise AIError(422, "invalid_status", f"文档状态非法：{status}（可选 {list(status_labels)}）")
    version = str(payload.get("version") or (existing or {}).get("version") or "v1.0").strip()
    if len(version) > 20:
        raise AIError(422, "invalid_version", "版本号不能超过 20 字")
    source = str(payload.get("source") or (existing or {}).get("source") or "页面录入（合成样例）").strip()
    owner = str(payload.get("owner") or (existing or {}).get("owner") or _role_label(role)).strip()

    content_changed = existing is None or content != str(existing.get("content") or "")
    if content_changed:
        chunks = _chunk_content(content, industry)
    else:
        chunks = existing.get("chunks", [])
    timestamp = _now()
    record = {
        "id": doc_id or new_id("kb"),
        "title": title,
        "industry": industry_id,
        "version": version,
        "status": status,
        "source": source,
        "owner": owner,
        "content": content,
        "chunkCount": len(chunks),
        "chunks": chunks,
        "keywords": _doc_keywords(chunks),
        "createdAt": (existing or {}).get("createdAt", timestamp),
        "updatedAt": timestamp,
        "createdBy": (existing or {}).get("createdBy", role),
        "updatedBy": role,
        "seed": bool((existing or {}).get("seed", False)) and not content_changed,
        "autoChunked": content_changed,
    }
    store().put("docs", record["id"], record)
    _log_event("knowledge.write", role, record["id"], True,
               f"{'更新' if existing else '新建'}《{title}》 {version}，{len(chunks)} 块，状态 {status}")
    return _doc_public(record, include_chunks=True)


def list_knowledge(industry: str | None = None, status: str | None = None) -> dict[str, Any]:
    ensure_seed()
    industry_id = industry or current_industry()
    info = _industry(industry_id)
    docs = [d for d in store().list("docs", 1000) if d.get("industry") == industry_id]
    if status:
        if status not in engine_config().get("statusLabels", {}).get("knowledge", {}):
            raise AIError(422, "invalid_status", f"未知文档状态：{status}")
        docs = [d for d in docs if d.get("status") == status]
    docs = sorted(docs, key=lambda d: (d.get("updatedAt") or "", d["id"]), reverse=True)
    return {
        "industry": industry_id,
        "industryName": info["name"],
        "documents": [_doc_brief(d) for d in docs],
        "counts": {
            "total": len(docs),
            "published": len([d for d in docs if d.get("status") == "published"]),
            "chunks": sum(len(d.get("chunks", [])) for d in docs),
        },
        "statusLabels": engine_config().get("statusLabels", {}).get("knowledge", {}),
    }


def get_knowledge(doc_id: str) -> dict[str, Any]:
    ensure_seed()
    doc = store().get("docs", doc_id)
    if not doc:
        raise AIError(404, "doc_not_found", f"知识文档不存在：{doc_id}")
    industry = _industry(doc["industry"])
    return {
        "document": _doc_public(doc, include_chunks=True),
        "industryName": industry["name"],
        "glossary": industry.get("glossary", []),
    }


def search_knowledge(query: str, industry: str | None = None, top_k: int | None = None,
                     role: str = "admin") -> dict[str, Any]:
    _check_role(role, "knowledge.search")
    ensure_seed()
    text = str(query or "").strip()
    if not text:
        raise AIError(400, "empty_query", "检索词不能为空，请输入术语或问题关键词")
    limits = engine_config().get("limits", {})
    if len(text) > int(limits.get("queryMaxChars", 200)):
        raise AIError(422, "query_too_long", f"检索词不能超过 {limits.get('queryMaxChars', 200)} 字")
    industry_id = industry or current_industry()
    info = _industry(industry_id)
    search_cfg = engine_config().get("search", {})
    try:
        limit = int(top_k if top_k is not None else search_cfg.get("topKDefault", 3))
    except (TypeError, ValueError):
        raise AIError(422, "invalid_topk", "topK 必须是整数")
    if limit < 1 or limit > int(search_cfg.get("topKMax", 8)):
        raise AIError(422, "invalid_topk", f"topK 必须在 1–{search_cfg.get('topKMax', 8)} 之间")
    if not industry_id:
        raise AIError(422, "invalid_industry", "缺少行业参数")

    started = time.perf_counter()
    docs = [
        d for d in store().list("docs", 1000)
        if d.get("industry") == industry_id and d.get("status") == "published"
    ]
    hits: list[dict[str, Any]] = []
    scanned_chunks = 0
    min_score = int(search_cfg.get("minScore", 2))
    for doc in docs:
        for chunk in doc.get("chunks", []):
            scanned_chunks += 1
            score = _score_chunk(text, doc, chunk, info)
            if score < min_score:
                continue
            hits.append({
                "citation": f"{doc['id']}#{chunk['id']}",
                "docId": doc["id"],
                "docTitle": doc["title"],
                "docVersion": doc.get("version"),
                "docSource": doc.get("source"),
                "chunkId": chunk["id"],
                "chunkIndex": chunk["index"],
                "text": chunk["text"],
                "keywords": chunk.get("keywords", []),
                "score": score,
            })
    hits.sort(key=lambda h: (-h["score"], h["docId"], h["chunkId"]))
    hits = hits[:limit]
    took_ms = round((time.perf_counter() - started) * 1000, 2)
    suggestions: list[str] = []
    if not hits:
        titles = "、".join(f"《{d['title']}》" for d in docs[:4]) or "暂无已发布文档"
        suggestions = [
            "换一个更短的关键词，例如「工期」「报价」「含水率」「木蜡油」",
            "确认相关文档状态为「已发布」；草稿文档不参与检索",
            f"当前行业已发布文档：{titles}",
        ]
    return {
        "query": text,
        "industry": industry_id,
        "industryName": info["name"],
        "hits": hits,
        "count": len(hits),
        "topK": limit,
        "tookMs": took_ms,
        "scanned": {"documents": len(docs), "chunks": scanned_chunks},
        "suggestions": suggestions,
        "engine": engine_config().get("engine", {}).get("label", "本地规则引擎"),
    }

# --------------------------------------------------------------------------- #
# 智能体：会话 / 意图路由 / 工具调用
# --------------------------------------------------------------------------- #
def _session_public(session: dict[str, Any], include_messages: bool = False) -> dict[str, Any]:
    payload = {
        "id": session["id"], "title": session["title"], "industry": session["industry"],
        "industryName": _industry(session["industry"])["name"],
        "agentId": session["agentId"], "agentName": session["agentName"],
        "createdBy": session["createdBy"], "createdAt": session["createdAt"],
        "updatedAt": session["updatedAt"], "messageCount": len(session.get("messages", [])),
    }
    if include_messages:
        payload["messages"] = session.get("messages", [])
    return payload


def create_session(payload: dict[str, Any], role: str = "admin") -> dict[str, Any]:
    _check_role(role, "agent.chat")
    ensure_seed()
    industry_id = str(payload.get("industry") or current_industry()).strip()
    industry = _industry(industry_id)
    agent_cfg = industry.get("agents", [{}])[0]
    if not agent_cfg:
        raise AIError(500, "agent_missing", f"行业 {industry_id} 未配置智能体")
    timestamp = _now()
    session = {
        "id": new_id("sess"),
        "title": str(payload.get("title") or f"{industry['name']} · 新会话").strip()[:80],
        "industry": industry_id,
        "agentId": agent_cfg["id"],
        "agentName": agent_cfg["name"],
        "createdBy": role,
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "messages": [],
    }
    store().put("sessions", session["id"], session)
    _log_event("agent.chat", role, session["id"], True, f"创建会话「{session['title']}」")
    result = _session_public(session)
    result.update({
        "starterQuestions": agent_cfg.get("starterQuestions", []),
        "engine": engine_config().get("engine", {}).get("label", "本地规则引擎"),
    })
    return result


def get_session(session_id: str) -> dict[str, Any]:
    ensure_seed()
    session = store().get("sessions", session_id)
    if not session:
        raise AIError(404, "session_not_found", f"会话不存在：{session_id}")
    industry = _industry(session["industry"])
    agent_cfg = industry.get("agents", [{}])[0]
    result = _session_public(session, include_messages=True)
    result["starterQuestions"] = agent_cfg.get("starterQuestions", [])
    result["toolCatalog"] = agent_cfg.get("tools", [])
    result["engine"] = engine_config().get("engine", {}).get("label", "本地规则引擎")
    return result


def _parse_budget(value: Any) -> tuple[int | None, str, str]:
    if value is None:
        return None, "CNY", ""
    raw = str(value).strip()
    if not raw:
        return None, "CNY", ""
    match = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(万|w|千|k|元|円|日元|美元|usd|cny|rmb|jpy|¥|￥|\$)?", raw, re.I)
    if not match:
        return None, "CNY", raw
    try:
        number = float(match.group(1).replace(",", ""))
    except ValueError:
        return None, "CNY", raw
    unit = (match.group(2) or "").lower()
    multiplier = 1.0
    if unit in ("万", "w"):
        multiplier = 10000.0
    elif unit in ("千", "k"):
        multiplier = 1000.0
    low = raw.lower()
    if "$" in raw or "usd" in low or "美元" in raw:
        currency = "USD"
    elif "円" in raw or "日元" in raw or "jpy" in low:
        currency = "JPY"
    else:
        currency = "CNY"
    cents = int(round(number * multiplier * 100))
    return cents, currency, raw


def _country_code(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "未填写"
    if re.fullmatch(r"[A-Za-z]{2}", raw):
        return raw.upper()
    low = raw.lower()
    for hint in engine_config().get("countryHints", []):
        for term in hint.get("terms", []):
            if str(term).lower() in low:
                return hint["code"]
    return raw.upper()


def _country_label(code: str) -> str:
    for hint in engine_config().get("countryHints", []):
        if hint.get("code") == code:
            return hint.get("label", code)
    return code


def _score_step(industry: dict[str, Any]) -> dict[str, Any] | None:
    for template in industry.get("workflowTemplates", []):
        for step in template.get("steps", []):
            if step.get("type") in ("score", "score_lead"):
                return step
    return None


def score_lead(industry: dict[str, Any], budget_cents: int | None, country_code: str,
               currency: str = "CNY", step_config: dict[str, Any] | None = None) -> dict[str, Any]:
    step = _score_step(industry) or {}
    rules = step.get("rules") or {}
    config = step_config or step.get("config") or {}
    priority = list(rules.get("priorityCountries") or config.get("priorityCountries") or ["CN"])
    threshold_a = int(rules.get("gradeA") or config.get("aBudgetCents") or 12000000)
    threshold_b = int(rules.get("gradeB") or config.get("bBudgetCents") or 3000000)
    reasons: list[str] = []
    if not budget_cents:
        reasons.append("未填写预算，按 C 级人工跟进")
        return {"grade": "C", "reasons": reasons}
    if budget_cents >= threshold_a:
        grade = "A"
        reasons.append(f"预算 {budget_cents // 100:,} {currency}，达到 A 级阈值")
    elif country_code in priority and budget_cents >= threshold_b:
        grade = "A"
        reasons.append(f"优先市场 {_country_label(country_code)}，预算达到 {threshold_b // 100:,} {currency}")
    elif budget_cents >= threshold_b:
        grade = "B"
        reasons.append(f"预算达到 B 级阈值 {threshold_b // 100:,} {currency}")
    elif country_code in priority:
        grade = "B"
        reasons.append(f"优先市场 {_country_label(country_code)}，按 B 级跟进")
    else:
        grade = "C"
        reasons.append("预算低于 B 级阈值，按 C 级培育")
    if currency != "CNY":
        reasons.append(f"预算按提交币种 {currency} 原值分档，未做汇率换算")
    return {"grade": grade, "reasons": reasons}


def _validate_lead(payload: dict[str, Any], role: str, source: str,
                   industry_id: str | None = None) -> dict[str, Any]:
    ensure_seed()
    ind_id = str(payload.get("industry") or industry_id or current_industry()).strip()
    industry = _industry(ind_id)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise AIError(422, "missing_name", "联系人姓名不能为空")
    if len(name) > 40:
        raise AIError(422, "name_too_long", "联系人姓名不能超过 40 字")
    email = str(payload.get("email") or "").strip().lower()
    if not email:
        raise AIError(422, "missing_email", "邮箱不能为空")
    if len(email) > 120 or not re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", email):
        raise AIError(422, "invalid_email", "邮箱格式不正确，请填写如 name@example.com 的地址")
    country_raw = str(payload.get("country") or "").strip()
    country = _country_code(country_raw) if country_raw else "CN"
    if not country:
        country = "CN"
    interest = str(payload.get("interest") or "").strip()
    if not interest:
        raise AIError(422, "missing_interest", "请填写感兴趣的品类或需求")
    if len(interest) > 120:
        raise AIError(422, "interest_too_long", "需求描述不能超过 120 字")
    message = str(payload.get("message") or "").strip()
    if len(message) > 2000:
        raise AIError(422, "message_too_long", "留言不能超过 2000 字")
    lang = str(payload.get("lang") or "zh").strip()
    if lang not in _languages():
        raise AIError(422, "invalid_lang", f"不支持的语言：{lang}")
    budget_cents, currency, budget_text = _parse_budget(payload.get("budget"))
    timestamp = _now()
    lead = {
        "id": new_id("lead"),
        "industry": ind_id,
        "industryName": industry["name"],
        "name": name,
        "email": email,
        "country": country,
        "countryLabel": _country_label(country),
        "interest": interest,
        "budgetText": budget_text,
        "budgetCents": budget_cents,
        "currency": currency,
        "message": message,
        "lang": lang,
        "stage": "new",
        "stageLabel": industry["crmStages"][0]["label"],
        "status": "open",
        "notes": [],
        "history": [{"at": timestamp, "from": None, "to": "new", "by": role, "note": "创建线索"}],
        "score": score_lead(industry, budget_cents, country, currency),
        "source": source,
        "createdBy": role,
        "createdAt": timestamp,
        "updatedAt": timestamp,
    }
    return lead


def create_lead(payload: dict[str, Any], role: str = "admin", source: str = "manual") -> dict[str, Any]:
    _check_role(role, "lead.create")
    lead = _validate_lead(payload, role, source)
    store().put("leads", lead["id"], lead)
    _log_event("lead.create", role, lead["id"], True,
               f"线索 {lead['name']} / {lead['country']} 写入 CRM，来源 {source}，评级 {lead['score']['grade']}")
    return lead


def create_inquiry(payload: dict[str, Any], role: str = "admin") -> dict[str, Any]:
    """询盘表单入口：校验后写入与智能体 create_lead 共用的 leads 集合。"""

    _check_role(role, "lead.create")
    lead = _validate_lead(payload, role, "inquiry-form")
    store().put("leads", lead["id"], lead)
    _log_event("lead.create", role, lead["id"], True,
               f"询盘表单写入线索 {lead['name']}，阶段 new，评级 {lead['score']['grade']}")
    return {
        "lead": lead,
        "stage": lead["stage"],
        "message": f"询盘已写入 CRM：线索 {lead['id']}，阶段「{lead['stageLabel']}」，评级 {lead['score']['grade']}（本地规则）。",
        "warning": "演示环境：邮箱、姓名、预算均为合成样例，不会真的发送邮件。",
    }


def list_leads(industry: str | None = None, stage: str | None = None) -> dict[str, Any]:
    ensure_seed()
    industry_id = industry or current_industry()
    info = _industry(industry_id)
    stages = info.get("crmStages", [])
    if stage and stage not in [s["id"] for s in stages]:
        raise AIError(422, "invalid_stage", f"未知 CRM 阶段：{stage}")
    leads = [lead for lead in store().list("leads", 2000) if lead.get("industry") == industry_id]
    if stage:
        leads = [lead for lead in leads if lead.get("stage") == stage]
    leads = sorted(leads, key=lambda lead: (lead.get("createdAt") or "", lead["id"]), reverse=True)
    counts = {s["id"]: {"label": s["label"], "count": 0} for s in stages}
    for lead in leads:
        if lead.get("stage") in counts:
            counts[lead["stage"]]["count"] += 1
    return {
        "industry": industry_id,
        "industryName": info["name"],
        "stages": stages,
        "leads": leads,
        "counts": counts,
        "total": len(leads),
        "open": len([l for l in leads if l.get("stage") not in ("won", "lost")]),
        "engine": engine_config().get("engine", {}).get("label", "本地规则引擎"),
    }


def update_lead(lead_id: str, payload: dict[str, Any], role: str = "admin") -> dict[str, Any]:
    _check_role(role, "lead.update")
    ensure_seed()
    lead = store().get("leads", lead_id)
    if not lead:
        raise AIError(404, "lead_not_found", f"线索不存在：{lead_id}")
    industry = _industry(lead["industry"])
    stage_ids = [stage["id"] for stage in industry.get("crmStages", [])]
    stage = str(payload.get("stage") or "").strip()
    note_text = str(payload.get("note") or "").strip()
    if not stage and not note_text:
        raise AIError(422, "nothing_to_update", "请提供 stage 或 note 至少一项")
    if stage and stage not in stage_ids:
        raise AIError(422, "invalid_stage", f"未知 CRM 阶段：{stage}（可选 {stage_ids}）")
    if len(note_text) > 500:
        raise AIError(422, "note_too_long", "备注不能超过 500 字")
    timestamp = _now()
    before = lead.get("stage")
    if stage and stage != before:
        lead["stage"] = stage
        lead["stageLabel"] = next((s["label"] for s in industry["crmStages"] if s["id"] == stage), stage)
        lead["status"] = "open" if stage not in ("won", "lost") else "closed"
        lead.setdefault("history", []).append({
            "at": timestamp, "from": before, "to": stage, "by": role, "note": note_text or "阶段推进",
        })
        if note_text:
            lead.setdefault("notes", []).append({"at": timestamp, "by": role, "text": note_text})
    elif note_text:
        lead.setdefault("notes", []).append({"at": timestamp, "by": role, "text": note_text})
        lead.setdefault("history", []).append({
            "at": timestamp, "from": before, "to": before, "by": role, "note": note_text,
        })
    lead["updatedAt"] = timestamp
    store().put("leads", lead_id, lead)
    _log_event("lead.update", role, lead_id, True,
               f"线索阶段 {before or '未设置'} → {lead['stage']}；备注：{note_text or '无'}")
    return lead


def _lead_fields_from_text(text: str, industry: dict[str, Any]) -> dict[str, Any]:
    email_match = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)
    email = email_match.group(0).lower() if email_match else ""
    name = ""
    for pattern in (
        r"联系人[：:\s]*([^\s，,。;；]{1,20})",
        r"姓名[：:\s]*([^\s，,。;；]{1,20})",
        r"name\s*(?:is|:)\s*([A-Za-z][A-Za-z .'\-]{1,30})",
    ):
        found = re.search(pattern, text, re.I)
        if found:
            name = found.group(1).strip()
            break
    if not name:
        found_cn = re.search(r"([\u4e00-\u9fa5]{1,4}(?:先生|女士|小姐|老师))", text)
        if found_cn:
            name = found_cn.group(1)
    if not name and email:
        name = email.split("@")[0] + "（邮箱来客）"
    interest = ""
    for pattern in (
        r"(?:想做|需要|想定制|想采购|定制|咨询|想咨询|了解|想了解|关注|想要|想买|想订)[：:\s]*([^，,。;；]{2,30})",
        r"对([^，,。;；]{2,30})感兴趣",
        r"interest[：:\s]*([^，,。;；]{2,40})",
    ):
        found = re.search(pattern, text, re.I)
        if found:
            interest = found.group(1).strip()
            break
    if not interest:
        for term in industry.get("productTerms", []):
            term = str(term or "").strip()
            pos = text.find(term) if term else -1
            if pos < 0:
                continue
            left = text[:pos]
            cut = max((left.rfind(mark) for mark in "，,。;；"), default=-1)
            prefix = left[cut + 1:] if cut >= 0 else left[-6:]
            prefix = re.sub(r"^(?:请记录|记录|帮我|麻烦|预算[：:\s]*[0-9][0-9,.]*\s*(?:万|w|千|k|元)?)", "", prefix).strip()
            interest = (prefix[-6:] + term).strip()
            break
    budget = ""
    for pattern in (
        r"预算[：:\s]*(?:约|为|是)?\s*([0-9][0-9,.]*\s*(?:万|w|千|k|元|美元|usd|円|日元)?)",
        r"budget[：:\s]*(?:is|:)?\s*([0-9][0-9,.]*\s*(?:k|m|usd|cny|rmb|jpy)?)",
    ):
        found = re.search(pattern, text, re.I)
        if found:
            budget = found.group(1).strip()
            break
    country = "CN"
    low = text.lower()
    for hint in engine_config().get("countryHints", []):
        if any(str(term).lower() in low for term in hint.get("terms", [])):
            country = hint["code"]
            break
    return {
        "name": name, "email": email, "interest": interest,
        "budget": budget, "country": country, "message": text,
        "industry": industry["id"], "lang": "zh",
    }


def _route_agent(session: dict[str, Any], content: str, role: str) -> dict[str, Any]:
    industry = _industry(session["industry"])
    agent_cfg = industry.get("agents", [{}])[0]
    tools = agent_cfg.get("tools", [])
    low = content.lower()
    hints = agent_cfg.get("intentHints", {})
    marker = lambda key: any(token.lower() in low for token in hints.get(key, []))
    has_email = bool(re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", content))
    question = bool(re.search(r"[?？]|怎么|如何|多少|多久|是否|能不能|可以吗|什么|why|how|what|when|cost|price", low))
    workflow_intent = marker("workflow") or any(k in low for k in ("自动化", "工作流", "workflow", "自动运行"))
    lead_intent = has_email or marker("lead")
    if workflow_intent:
        return {"intent": "draft_workflow", "intentLabel": "生成工作流草稿",
                "reply": "", "toolCalls": [], "citations": []}
    if lead_intent and not (question and not has_email):
        return {"intent": "create_lead", "intentLabel": "写入 CRM 线索",
                "reply": "", "toolCalls": [], "citations": []}
    return {"intent": "search_knowledge", "intentLabel": "知识库检索", "reply": "", "toolCalls": [], "citations": []}


def _tool_search(content: str, industry_id: str, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    result = search_knowledge(content, industry_id, 3, role)
    duration = round((time.perf_counter() - started) * 1000, 2)
    hits = result["hits"]
    citations = [{
        "citation": hit["citation"], "docId": hit["docId"], "docTitle": hit["docTitle"],
        "docVersion": hit["docVersion"], "chunkId": hit["chunkId"], "score": hit["score"],
        "text": hit["text"],
    } for hit in hits]
    args = {"query": content[:120], "industry": industry_id, "topK": 3}
    if hits:
        summary = f"命中 {len(hits)} 个知识片段，最高分 {hits[0]['score']}，引用 " + "、".join(h["citation"] for h in hits)
    else:
        summary = "未命中已发布知识片段（诚实返回空结果）"
    tool_call = {
        "tool": "search_knowledge", "args": args, "resultSummary": summary,
        "ok": True, "durationMs": duration, "hits": len(hits),
    }
    return tool_call, {"search": result, "citations": citations}


def _tool_lead(content: str, role: str, industry: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    fields = _lead_fields_from_text(content, industry)
    started = time.perf_counter()
    if not fields["email"]:
        duration = round((time.perf_counter() - started) * 1000, 2)
        tool_call = {
            "tool": "create_lead", "args": {"name": fields["name"], "email": ""},
            "resultSummary": "缺少邮箱，未写入 CRM（请补充邮箱后重试）",
            "ok": False, "durationMs": duration,
        }
        return tool_call, {"missing": ["email"], "lead": None}
    try:
        lead = create_lead(fields, role, source="agent-chat")
    except AIError as exc:
        duration = round((time.perf_counter() - started) * 1000, 2)
        tool_call = {
            "tool": "create_lead", "args": {"name": fields["name"], "email": fields["email"]},
            "resultSummary": f"{exc.error}：{exc.message}", "ok": False, "durationMs": duration,
        }
        return tool_call, {"error": exc.error, "message": exc.message, "lead": None}
    duration = round((time.perf_counter() - started) * 1000, 2)
    tool_call = {
        "tool": "create_lead",
        "args": {"name": lead["name"], "email": lead["email"], "country": lead["country"],
                 "interest": lead["interest"], "budget": lead["budgetText"]},
        "resultSummary": f"线索 {lead['id']} 写入 CRM，阶段 {lead['stageLabel']}，评级 {lead['score']['grade']}",
        "ok": True, "durationMs": duration, "leadId": lead["id"],
    }
    return tool_call, {"lead": lead, "missing": []}


def _reply_search(content: str, industry: dict[str, Any], role: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, dict[str, Any]]:
    tool_call, payload = _tool_search(content, industry["id"], role)
    hits = payload["search"]["hits"]
    if hits:
        lines = ["根据本地知识库检索，以下片段可作为依据（引用格式 文档ID#块ID）："]
        for hit in hits:
            snippet = re.sub(r"\s+", " ", hit["text"])[:120]
            lines.append(f"[{hit['citation']}] {snippet}")
        lines.append("以上内容来自已发布文档，最终结论请以全文与人工复核为准。")
        reply = "\n".join(lines)
    else:
        docs = [d for d in store().list("docs", 1000)
                if d.get("industry") == industry["id"] and d.get("status") == "published"]
        titles = "、".join(f"《{d['title']}》" for d in docs[:4]) or "暂无已发布文档"
        reply = (
            "知识库里暂时没有直接匹配的内容，我不会编造答案。可以换用更短的关键词，"
            f"或补充行业术语；当前已发布文档：{titles}。也可以留下邮箱，由人工跟进。"
        )
    return [tool_call], payload["citations"], reply, payload


def _reply_lead(content: str, role: str, industry: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, dict[str, Any]]:
    tool_call, payload = _tool_lead(content, role, industry)
    tool_calls = [tool_call] if tool_call else []
    if payload and payload.get("lead"):
        lead = payload["lead"]
        reply = (
            f"已把询盘写入 CRM：线索 {lead['id']}，阶段「{lead['stageLabel']}」，"
            f"评级 {lead['score']['grade']}，负责人可在 CRM 面板推进。"
            "本回复由本地确定性规则生成，未调用外部大模型；请人工复核预算与需求后再报价。"
        )
        return tool_calls, [], reply, payload
    if payload and payload.get("error") == "forbidden":
        return tool_calls, [], f"当前角色无法写入 CRM：{payload.get('message', '权限不足')}。请切换到运营或管理员角色。", payload
    return tool_calls, [], "要登记线索，请补充可用的邮箱（如 name@example.com）和联系人姓名，我再写入 CRM。", payload or {}


def _reply_workflow(content: str, role: str, industry: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, dict[str, Any]]:
    started = time.perf_counter()
    templates = industry.get("workflowTemplates", [])
    template = templates[0] if templates else None
    if not template:
        return [], [], "当前行业没有可用的工作流模板。", {}
    try:
        _check_role(role, "workflow.write")
        workflow = create_workflow({"templateId": template["id"], "name": f"AI 草稿：{template['name']}"}, role)
        ok = True
        summary = f"已创建草稿工作流 {workflow['id']}，共 {len(workflow['steps'])} 步，等待人工确认后运行"
        reply = (
            f"已按「{template['name']}」生成工作流草稿 {workflow['id']}（状态 draft），"
            "包含查知识库、评分、写 CRM、生成报价草稿与通知五类步骤。"
            "请到工作流面板检查输入字段后运行；自动化只做辅助，不会自动对外发送邮件。"
        )
    except AIError as exc:
        ok = False
        summary = f"{exc.error}：{exc.message}"
        workflow = None
        reply = f"当前角色无法生成工作流草稿：{exc.message}。请切换到运营或管理员角色。"
    duration = round((time.perf_counter() - started) * 1000, 2)
    tool_call = {
        "tool": "draft_workflow", "args": {"templateId": template["id"]},
        "resultSummary": summary, "ok": ok, "durationMs": duration,
    }
    if workflow:
        tool_call["workflowId"] = workflow["id"]
    return [tool_call], [], reply, {"workflow": workflow}


def send_session_message(session_id: str, payload: dict[str, Any], role: str = "admin") -> dict[str, Any]:
    _check_role(role, "agent.chat")
    ensure_seed()
    session = store().get("sessions", session_id)
    if not session:
        raise AIError(404, "session_not_found", f"会话不存在：{session_id}")
    content = str(payload.get("content") or "").strip()
    if not content:
        raise AIError(422, "empty_message", "消息内容不能为空")
    max_chars = int(engine_config().get("limits", {}).get("messageMaxChars", 2000))
    if len(content) > max_chars:
        raise AIError(422, "message_too_long", f"消息不能超过 {max_chars} 字")
    max_messages = int(engine_config().get("limits", {}).get("sessionMessages", 200))
    if len(session.get("messages", [])) >= max_messages:
        raise AIError(422, "session_full", f"单个会话最多 {max_messages} 条消息，请新建会话")
    industry = _industry(session["industry"])
    timestamp = _now()
    user_message = {
        "id": new_id("msg"), "sender": "user", "role": role, "content": content,
        "at": timestamp,
    }
    session.setdefault("messages", []).append(user_message)
    route = _route_agent(session, content, role)
    citations: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    if route["intent"] == "create_lead":
        tool_calls, citations, reply, extra = _reply_lead(content, role, industry)
    elif route["intent"] == "draft_workflow":
        tool_calls, citations, reply, extra = _reply_workflow(content, role, industry)
    else:
        tool_calls, citations, reply, extra = _reply_search(content, industry, role)
    assistant_message = {
        "id": new_id("msg"), "sender": "assistant", "role": session["agentId"],
        "content": reply, "at": _now(), "intent": route["intent"],
        "intentLabel": route["intentLabel"], "toolCalls": tool_calls,
        "citations": citations, "engine": "local-rules",
    }
    session["messages"].append(assistant_message)
    if len(session["messages"]) <= 2 and str(session.get("title", "")).endswith("新会话"):
        session["title"] = re.sub(r"\s+", " ", content)[:28]
    session["updatedAt"] = _now()
    session["lastRole"] = role
    store().put("sessions", session_id, session)
    _log_event("agent.chat", role, session_id, True,
               f"{route['intentLabel']}；工具 {','.join(c['tool'] for c in tool_calls) or '无'}；引用 {len(citations)}")
    return {
        "session": _session_public(session),
        "userMessage": user_message,
        "assistantMessage": assistant_message,
        "reply": reply,
        "intent": route["intent"],
        "intentLabel": route["intentLabel"],
        "toolCalls": tool_calls,
        "citations": citations,
        "engine": engine_config().get("engine", {}).get("label", "本地规则引擎"),
        "disclaimer": "本地意图路由 + 关键词检索，非外部大模型；结果需人工复核。",
    }

# --------------------------------------------------------------------------- #
# 工作流引擎
# --------------------------------------------------------------------------- #
def _type_label(step_type: str) -> str:
    return engine_config().get("stepTypeLabels", {}).get(step_type, step_type)


def _template_public(template: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": template["id"], "name": template["name"], "version": template.get("version", "v1.0"),
        "status": template.get("status", "active"), "description": template.get("description", ""),
        "trigger": template.get("trigger", {}), "requiredInputs": template.get("requiredInputs", []),
        "inputExample": template.get("inputExample", {}),
        "steps": [{
            "name": step["name"], "type": step["type"], "typeLabel": _type_label(step["type"]),
            "condition": step.get("condition"),
        } for step in template.get("steps", [])],
    }


def _workflow_public(workflow: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": workflow["id"], "templateId": workflow.get("templateId"), "name": workflow["name"],
        "industry": workflow["industry"], "industryName": _industry(workflow["industry"])["name"],
        "status": workflow.get("status", "draft"),
        "statusLabel": engine_config().get("statusLabels", {}).get("workflow", {}).get(
            workflow.get("status"), workflow.get("status")),
        "createdBy": workflow.get("createdBy"), "createdAt": workflow.get("createdAt"),
        "updatedAt": workflow.get("updatedAt"), "runCount": workflow.get("runCount", 0),
        "lastRunId": workflow.get("lastRunId"),
        "steps": [{
            "name": step["name"], "type": step["type"], "typeLabel": _type_label(step["type"]),
            "condition": step.get("condition"), "config": step.get("config", {}),
        } for step in workflow.get("steps", [])],
    }


def _run_brief(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": run["id"], "workflowId": run["workflowId"], "workflowName": run.get("workflowName"),
        "industry": run.get("industry"), "status": run["status"],
        "statusLabel": engine_config().get("statusLabels", {}).get("run", {}).get(run["status"], run["status"]),
        "attempt": run.get("attempt", 1), "retryOf": run.get("retryOf"),
        "startedAt": run.get("startedAt"), "finishedAt": run.get("finishedAt"),
        "durationMs": run.get("durationMs"), "leadId": run.get("leadId"), "grade": run.get("grade"),
        "failedStep": run.get("failedStep"), "stepCount": len(run.get("steps", [])),
        "inputSummary": {
            "name": run.get("input", {}).get("name"),
            "email": run.get("input", {}).get("email"),
            "interest": run.get("input", {}).get("interest"),
            "budget": run.get("input", {}).get("budget"),
        },
    }


def _workflow_or_404(workflow_id: str) -> dict[str, Any]:
    workflow = store().get("workflows", workflow_id)
    if not workflow:
        raise AIError(404, "workflow_not_found", f"工作流不存在：{workflow_id}")
    return workflow


def create_workflow(payload: dict[str, Any], role: str = "admin") -> dict[str, Any]:
    _check_role(role, "workflow.write")
    ensure_seed()
    industry_id = str(payload.get("industry") or current_industry()).strip()
    industry = _industry(industry_id)
    templates = industry.get("workflowTemplates", [])
    template_id = str(payload.get("templateId") or "").strip()
    if not template_id:
        if not templates:
            raise AIError(422, "template_required", "请提供 templateId")
        template_id = templates[0]["id"]
    template = next((t for t in templates if t["id"] == template_id), None)
    if not template:
        raise AIError(422, "template_not_found", f"行业 {industry_id} 没有模板 {template_id}",
                      {"templates": [t["id"] for t in templates]})
    name = str(payload.get("name") or f"{template['name']} · 实例").strip()
    if not name:
        raise AIError(422, "missing_name", "工作流名称不能为空")
    if len(name) > 80:
        raise AIError(422, "name_too_long", "工作流名称不能超过 80 字")
    timestamp = _now()
    workflow = {
        "id": new_id("wf"),
        "templateId": template["id"],
        "name": name,
        "industry": industry_id,
        "status": "draft",
        "createdBy": role,
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "runCount": 0,
        "lastRunId": None,
        "steps": json.loads(json.dumps(template.get("steps", []), ensure_ascii=False)),
        "requiredInputs": list(template.get("requiredInputs", [])),
        "inputExample": dict(template.get("inputExample", {})),
        "templateVersion": template.get("version", "v1.0"),
    }
    store().put("workflows", workflow["id"], workflow)
    _log_event("workflow.write", role, workflow["id"], True,
               f"创建「{name}」（模板 {template['id']}，{len(workflow['steps'])} 步）")
    return _workflow_public(workflow)


def list_workflows(industry: str | None = None) -> dict[str, Any]:
    ensure_seed()
    industry_id = industry or current_industry()
    info = _industry(industry_id)
    workflows = [w for w in store().list("workflows", 500) if w.get("industry") == industry_id]
    workflows = sorted(workflows, key=lambda w: (w.get("createdAt") or "", w["id"]), reverse=True)
    return {
        "industry": industry_id,
        "industryName": info["name"],
        "templates": [_template_public(t) for t in info.get("workflowTemplates", [])],
        "workflows": [_workflow_public(w) for w in workflows],
        "count": len(workflows),
        "engine": engine_config().get("engine", {}).get("label", "本地规则引擎"),
    }


def get_workflow(workflow_id: str) -> dict[str, Any]:
    ensure_seed()
    workflow = _workflow_or_404(workflow_id)
    runs = [r for r in store().list("runs", 1000) if r.get("workflowId") == workflow_id]
    runs = sorted(runs, key=lambda r: (r.get("startedAt") or "", r["id"]), reverse=True)[:20]
    result = _workflow_public(workflow)
    result["runs"] = [_run_brief(r) for r in runs]
    return result


def _normalize_input(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise AIError(422, "invalid_input", "工作流 input 必须是 JSON 对象")
    data: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, str):
            data[str(key)] = value.strip()
        elif isinstance(value, (int, float, bool)) or value is None:
            data[str(key)] = value
        else:
            raise AIError(422, "invalid_input", f"输入字段 {key} 必须是字符串或数字")
    return data


def _render_template(text: str, context: dict[str, Any]) -> str:
    def replace(match: re.Match) -> str:
        key = match.group(1)
        value = context.get(key)
        return "" if value is None else str(value)
    return re.sub(r"\{([A-Za-z0-9_]+)\}", replace, str(text))


def _condition_ok(condition: dict[str, Any], context: dict[str, Any]) -> bool:
    field = condition.get("field")
    op = condition.get("op", "eq")
    expected = condition.get("value")
    actual = context.get(field)
    try:
        if op == "eq":
            return str(actual) == str(expected)
        if op == "ne":
            return str(actual) != str(expected)
        if op == "in":
            return actual in expected if isinstance(expected, list) else False
        if op == "contains":
            return str(expected) in str(actual or "")
        if op in ("gt", "gte", "lt", "lte"):
            left = float(actual)
            right = float(expected)
            return {"gt": left > right, "gte": left >= right, "lt": left < right, "lte": left <= right}[op]
    except (TypeError, ValueError):
        return False
    return False


def _execute_step(step: dict[str, Any], context: dict[str, Any], industry: dict[str, Any],
                  role: str, run_id: str) -> tuple[str, dict[str, Any]]:
    step_type = step["type"]
    config = step.get("config", {}) or {}
    if step_type == "validate_input":
        required = config.get("required", [])
        missing = [field for field in required if not str(context.get(field) or "").strip()]
        if missing:
            raise AIError(422, "missing_input", f"缺少必填字段：{', '.join(missing)}", {"missing": missing})
        email_field = config.get("emailField")
        if email_field:
            email = str(context.get(email_field) or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", email):
                raise AIError(422, "invalid_email", f"邮箱格式不正确：{email or '空'}")
        enum_field = config.get("enumField")
        if enum_field and context.get(enum_field) not in config.get("enum", []):
            raise AIError(422, "invalid_enum",
                          f"字段 {enum_field} 必须是 {config.get('enum')} 之一")
        return f"必填字段齐全（{', '.join(required) or '无'}），格式校验通过", {}

    if step_type == "search_knowledge":
        field = config.get("queryField", "interest")
        query = str(context.get(field) or "").strip()
        suffix = str(config.get("querySuffix") or "").strip()
        if suffix:
            query = f"{query} {suffix}".strip()
        if not query:
            raise AIError(422, "empty_query", "检索步骤缺少查询内容")
        result = search_knowledge(query, industry["id"], int(config.get("topK", 2)), role)
        citations = [hit["citation"] for hit in result["hits"]]
        context["citations"] = citations
        context["knowledgeHits"] = len(citations)
        if citations:
            detail = f"检索「{query[:40]}」命中 {len(citations)} 段：" + "、".join(citations)
        else:
            detail = f"检索「{query[:40]}」未命中已发布片段（不阻断流程，后续步骤需人工复核）"
        return detail, {"citations": citations, "hits": len(citations)}

    if step_type == "score_lead":
        budget_cents, currency, _ = _parse_budget(context.get("budget"))
        country = _country_code(str(context.get("country") or "CN"))
        scored = score_lead(industry, budget_cents, country, currency, config)
        context["grade"] = scored["grade"]
        context["budgetText"] = context.get("budget") or "未填写"
        context["budgetCents"] = budget_cents
        context["currency"] = currency
        return f"线索评级 {scored['grade']}：" + "；".join(scored["reasons"]), {
            "grade": scored["grade"], "budgetCents": budget_cents,
        }

    if step_type == "create_lead":
        data = {
            "name": context.get("name"), "email": context.get("email"),
            "country": context.get("country") or "CN", "interest": context.get("interest"),
            "budget": context.get("budget"), "message": context.get("message") or "",
            "lang": context.get("lang") or "zh", "industry": industry["id"],
        }
        lead = create_lead(data, role, source=str(config.get("source") or "工作流"))
        context["leadId"] = lead["id"]
        context["lead"] = lead
        return f"线索 {lead['id']} 写入 CRM，阶段 {lead['stageLabel']}，评级 {lead['score']['grade']}", {
            "leadId": lead["id"], "grade": lead["score"]["grade"],
        }

    if step_type == "draft_quote":
        budget_cents, currency, _ = _parse_budget(context.get("budget"))
        base = config.get("baseRangeCents", [0, 0])
        low = int(base[0]) if len(base) > 0 else 0
        high = int(base[1]) if len(base) > 1 else low
        if budget_cents and budget_cents < low:
            note = f"预算 {budget_cents // 100:,} 低于基础区间下限；建议沟通缩量、替代材质或分期。"
        else:
            note = str(config.get("note") or "报价草稿需人工复核")
        deposit_pct = float(config.get("depositPct", 30))
        deposit = int(round(high * deposit_pct / 100))
        currency = str(config.get("currency") or currency)
        quote_id = new_id("quote")
        quote = {
            "id": quote_id, "runId": run_id, "workflowId": context.get("workflowId"),
            "industry": industry["id"], "leadId": context.get("leadId"),
            "lowCents": low, "highCents": high, "currency": currency,
            "depositCents": deposit, "depositPct": deposit_pct,
            "validityDays": int(config.get("validityDays", 7)),
            "minQty": int(config.get("minQty", 1)), "note": note,
            "budgetText": context.get("budget"), "status": "draft",
            "createdAt": _now(),
        }
        store().put("quotes", quote_id, quote)
        context["quoteId"] = quote_id
        context["quoteRange"] = f"{currency} {low // 100:,}–{high // 100:,}"
        return (f"报价草稿 {quote_id}：区间 {currency} {low // 100:,}–{high // 100:,}，"
                f"定金 {deposit_pct:.0f}%，有效期 {quote['validityDays']} 天；状态 draft，待人工复核"), {
            "quoteId": quote_id, "range": context["quoteRange"],
        }

    if step_type == "notify":
        message = _render_template(str(config.get("message") or "工作流完成"), context)
        notification_id = new_id("ntf")
        store().put("notifications", notification_id, {
            "id": notification_id, "runId": run_id, "to": config.get("to", "运营组"),
            "channel": config.get("channel", "in_app"), "message": message,
            "simulated": True, "createdAt": _now(),
        })
        return f"站内通知（模拟，不发送邮件/短信）→ {config.get('to', '运营组')}：{message}", {
            "notificationId": notification_id,
        }

    if step_type == "seo_check":
        lang = str(context.get("lang") or "zh")
        seo = _seo_payload(lang, industry)
        coverage = int(seo["coverage"]["bps"])
        minimum = int(config.get("minCoverageBps", 8000))
        context["coverageBps"] = coverage
        if coverage < minimum:
            raise AIError(422, "seo_coverage_low",
                          f"SEO 关键词覆盖率 {coverage / 100:.1f}% 低于阈值 {minimum / 100:.1f}%，请补充缺失关键词",
                          {"coverageBps": coverage, "missing": seo["coverage"]["missing"]})
        return f"SEO 关键词覆盖 {coverage / 100:.1f}%（阈值 {minimum / 100:.1f}%），检查项得分 {seo['score']}", {
            "coverageBps": coverage, "seoScore": seo["score"],
        }

    raise AIError(422, "unknown_step_type", f"未知步骤类型：{step_type}")


def _execute_run(workflow: dict[str, Any], input_data: dict[str, Any], role: str,
                 attempt: int = 1, retry_of: str | None = None) -> dict[str, Any]:
    industry = _industry(workflow["industry"])
    run_id = new_id("run")
    started_at = _now()
    run_started = time.perf_counter()
    context: dict[str, Any] = dict(input_data)
    context.update({
        "industry": industry["id"], "industryName": industry["name"],
        "workflowId": workflow["id"], "runId": run_id, "role": role,
    })
    steps: list[dict[str, Any]] = []
    failed_step: dict[str, Any] | None = None
    for index, step in enumerate(workflow.get("steps", []), start=1):
        if index > int(engine_config().get("workflow", {}).get("maxSteps", 20)):
            failed_step = {"index": index, "name": step.get("name"), "error": "max_steps"}
            break
        condition = step.get("condition")
        if condition and not _condition_ok(condition, context):
            steps.append({
                "index": index, "name": step["name"], "type": step["type"],
                "typeLabel": _type_label(step["type"]), "ok": True, "skipped": True,
                "detail": "条件不满足，跳过（未伪造执行结果）", "durationMs": 0,
            })
            continue
        step_started = time.perf_counter()
        try:
            detail, extra = _execute_step(step, context, industry, role, run_id)
        except AIError as exc:
            duration = round((time.perf_counter() - step_started) * 1000, 2)
            steps.append({
                "index": index, "name": step["name"], "type": step["type"],
                "typeLabel": _type_label(step["type"]), "ok": False,
                "detail": exc.message, "error": exc.error, "status": exc.status,
                "extra": exc.extra, "durationMs": duration,
            })
            failed_step = {"index": index, "name": step["name"], "error": exc.error,
                           "message": exc.message}
            break
        except Exception as exc:  # 防御性：步骤异常必须显式记录，不能静默成功
            duration = round((time.perf_counter() - step_started) * 1000, 2)
            steps.append({
                "index": index, "name": step["name"], "type": step["type"],
                "typeLabel": _type_label(step["type"]), "ok": False,
                "detail": f"步骤内部异常：{exc}", "error": "step_internal_error",
                "durationMs": duration,
            })
            failed_step = {"index": index, "name": step["name"], "error": "step_internal_error",
                           "message": str(exc)}
            break
        duration = round((time.perf_counter() - step_started) * 1000, 2)
        steps.append({
            "index": index, "name": step["name"], "type": step["type"],
            "typeLabel": _type_label(step["type"]), "ok": True,
            "detail": detail, "durationMs": duration, "extra": extra,
        })
    status = "failed" if failed_step else "success"
    finished_at = _now()
    run = {
        "id": run_id, "workflowId": workflow["id"], "workflowName": workflow.get("name"),
        "industry": industry["id"], "status": status,
        "statusLabel": engine_config().get("statusLabels", {}).get("run", {}).get(status, status),
        "input": input_data, "steps": steps, "failedStep": failed_step,
        "startedAt": started_at, "finishedAt": finished_at,
        "durationMs": round((time.perf_counter() - run_started) * 1000, 2),
        "attempt": attempt, "retryOf": retry_of, "role": role,
        "leadId": context.get("leadId"), "grade": context.get("grade"),
        "quoteId": context.get("quoteId"), "citations": context.get("citations", []),
        "createdAt": started_at,
    }
    store().put("runs", run_id, run)
    workflow["runCount"] = int(workflow.get("runCount", 0)) + 1
    workflow["lastRunId"] = run_id
    workflow["updatedAt"] = _now()
    if status == "success":
        workflow["status"] = "active"
    store().put("workflows", workflow["id"], workflow)
    _log_event("workflow.retry" if retry_of else "workflow.run", role, run_id,
               status == "success", f"{workflow['name']}：{status}，{len(steps)} 步")
    return run


def run_workflow(workflow_id: str, payload: dict[str, Any], role: str = "admin") -> dict[str, Any]:
    _check_role(role, "workflow.run")
    ensure_seed()
    workflow = _workflow_or_404(workflow_id)
    raw_input = payload.get("input", {})
    input_data = _normalize_input(raw_input)
    return _execute_run(workflow, input_data, role, attempt=1)


def retry_run(run_id: str, payload: dict[str, Any], role: str = "admin") -> dict[str, Any]:
    _check_role(role, "workflow.retry")
    ensure_seed()
    previous = store().get("runs", run_id)
    if not previous:
        raise AIError(404, "run_not_found", f"运行记录不存在：{run_id}")
    if previous.get("status") != "failed":
        raise AIError(409, "run_not_failed", "只有失败的运行可以重试")
    retry_limit = int(engine_config().get("workflow", {}).get("retryLimit", 3))
    attempt = int(previous.get("attempt", 1)) + 1
    if attempt > retry_limit:
        raise AIError(422, "retry_limit_exceeded", f"已超过最大重试次数（{retry_limit} 次尝试）")
    workflow = _workflow_or_404(previous["workflowId"])
    patch_raw = payload.get("input")
    if patch_raw is None:
        patch_raw = {key: value for key, value in payload.items() if key not in ("role",)}
    patch = _normalize_input(patch_raw)
    merged = dict(previous.get("input", {}))
    merged.update(patch)
    run = _execute_run(workflow, merged, role, attempt=attempt, retry_of=run_id)
    previous["retryRunId"] = run["id"]
    previous["retriedAt"] = _now()
    store().put("runs", run_id, previous)
    return run


def list_runs(workflow_id: str | None = None, industry: str | None = None,
              limit: int = 20) -> dict[str, Any]:
    ensure_seed()
    industry_id = industry or current_industry()
    _industry(industry_id)
    try:
        count = int(limit)
    except (TypeError, ValueError):
        raise AIError(422, "invalid_limit", "limit 必须是整数")
    count = max(1, min(count, int(engine_config().get("limits", {}).get("runListLimit", 50))))
    runs = [r for r in store().list("runs", 1000) if r.get("industry") == industry_id]
    if workflow_id:
        runs = [r for r in runs if r.get("workflowId") == workflow_id]
    runs = sorted(runs, key=lambda r: (r.get("startedAt") or "", r["id"]), reverse=True)[:count]
    status_counts: dict[str, int] = {}
    for run in runs:
        status_counts[run.get("status", "unknown")] = status_counts.get(run.get("status", "unknown"), 0) + 1
    return {
        "industry": industry_id,
        "runs": [_run_brief(r) for r in runs],
        "count": len(runs),
        "statusCounts": status_counts,
    }

# --------------------------------------------------------------------------- #
# 多语言独立站 / SEO / FDE 手册
# --------------------------------------------------------------------------- #
def _assert_lang(lang: str) -> str:
    value = str(lang or "").strip()
    if value not in _languages():
        raise AIError(422, "invalid_lang", f"不支持的语言：{value}（可选 {' / '.join(_languages())}）")
    return value


def _seo_payload(lang: str, industry: dict[str, Any]) -> dict[str, Any]:
    lang = _assert_lang(lang)
    site = industry.get("site", {}).get(lang)
    if not site:
        raise AIError(404, "site_not_found", f"行业 {industry['id']} 缺少 {lang} 站点文案")
    languages = _languages()
    title = str(site.get("title") or "")
    description = str(site.get("description") or "")
    keywords = [str(k) for k in site.get("keywords", [])]
    hero = site.get("hero", {}) or {}
    sections = site.get("sections", []) or []
    faq = site.get("faq", []) or []
    haystack = " ".join([
        title, description, str(hero.get("headline") or ""), str(hero.get("subline") or ""),
        str(hero.get("cta") or ""),
        " ".join(f"{s.get('heading', '')} {s.get('body', '')}" for s in sections),
        " ".join(f"{f.get('q', '')} {f.get('a', '')}" for f in faq),
    ])
    squashed = _squash(haystack)
    matched: list[str] = []
    missing: list[str] = []
    for keyword in keywords:
        if _squash(keyword) and _squash(keyword) in squashed:
            matched.append(keyword)
        else:
            missing.append(keyword)
    total = len(keywords)
    coverage_bps = int(round(len(matched) / total * 10000)) if total else 0
    checks = [
        {"id": "title_length", "label": "标题长度", "ok": 10 <= len(title) <= 70,
         "detail": f"{len(title)} 字符（建议 10–70）"},
        {"id": "description_length", "label": "描述长度", "ok": 40 <= len(description) <= 200,
         "detail": f"{len(description)} 字符（建议 40–200）"},
        {"id": "keywords_count", "label": "关键词数量", "ok": total >= 3,
         "detail": f"{total} 个（至少 3 个）"},
        {"id": "hero_present", "label": "首屏主文案", "ok": bool(hero.get("headline") and hero.get("subline")),
         "detail": "主标题与副标题均已配置" if hero.get("headline") and hero.get("subline") else "缺少主标题或副标题"},
        {"id": "sections_count", "label": "内容区块", "ok": len(sections) >= 3,
         "detail": f"{len(sections)} 个（至少 3 个）"},
        {"id": "faq_count", "label": "FAQ 条数", "ok": len(faq) >= 3,
         "detail": f"{len(faq)} 条（至少 3 条）"},
        {"id": "keyword_coverage", "label": "关键词覆盖", "ok": coverage_bps >= 8000,
         "detail": f"{coverage_bps / 100:.1f}%（阈值 80%）"},
        {"id": "alternates", "label": "三语 hreflang", "ok": set(industry.get("site", {})) >= {"zh", "en", "ja"},
         "detail": "zh / en / ja 三个语言版本均已配置"},
    ]
    score = int(round(len([c for c in checks if c["ok"]]) / len(checks) * 100))
    alternates = {
        code: f"/pages/ai.html?lang={code}&industry={industry['id']}"
        for code in languages
    }
    return {
        "lang": lang,
        "langLabel": languages.get(lang, lang),
        "industry": industry["id"],
        "industryName": industry["name"],
        "meta": {
            "title": title,
            "description": description,
            "keywords": keywords,
            "canonical": f"/pages/ai.html?lang={lang}&industry={industry['id']}",
            "robots": "noindex,nofollow（合成演示，禁止被搜索引擎收录）",
            "og": {"title": title, "description": description, "type": "website"},
            "alternates": alternates,
        },
        "coverage": {
            "matched": matched, "missing": missing, "total": total,
            "bps": coverage_bps, "pct": round(coverage_bps / 100, 1),
        },
        "checks": checks,
        "score": score,
        "thresholdBps": 8000,
        "note": "覆盖率为确定性字符串匹配，不代表真实搜索排名；发布前仍需人工审校。",
    }


def get_site(lang: str, industry_id: str | None = None) -> dict[str, Any]:
    ensure_seed()
    info = _industry(industry_id or current_industry())
    lang = _assert_lang(lang)
    site = info["site"].get(lang)
    if not site:
        raise AIError(404, "site_not_found", f"行业 {info['id']} 缺少 {lang} 站点文案")
    seo = _seo_payload(lang, info)
    return {
        "industry": info["id"],
        "industryName": info["name"],
        "lang": lang,
        "label": site.get("label", lang),
        "site": site,
        "seo": seo,
        "languages": [{"code": key, "label": val} for key, val in _languages().items()],
        "sampleData": True,
        "disclaimer": "站点文案为合成样例，不含真实客户、真实设备清单或版权归属；SEO 元数据仅用于演示。",
    }


def get_seo(lang: str, industry_id: str | None = None) -> dict[str, Any]:
    ensure_seed()
    info = _industry(industry_id or current_industry())
    lang = _assert_lang(lang)
    return {
        "industry": info["id"],
        "industryName": info["name"],
        "lang": lang,
        "seo": _seo_payload(lang, info),
        "sampleData": True,
        "note": "关键词覆盖为本地字符串匹配统计；不承诺真实搜索引擎排名。",
    }


def get_fde_handbook() -> dict[str, Any]:
    cfg = handbook_config()
    lines = [str(line) for line in cfg.get("lines", [])]
    markdown = "\n".join(lines)
    headings = []
    for line in lines:
        if line.startswith("## "):
            headings.append(line[3:].strip())
    return {
        "title": cfg.get("title", "FDE 驻企交付手册"),
        "version": cfg.get("version", "v1.0"),
        "updatedAt": cfg.get("updatedAt"),
        "markdown": markdown,
        "chars": len(markdown),
        "sections": len(headings),
        "headings": headings,
        "sampleData": True,
        "disclaimer": "手册为合成样例交付方法，不构成对真实客户、真实产能、法律效力或商业承诺的保证。",
    }

# --------------------------------------------------------------------------- #
# 配置 / 仪表盘 / 行业切换 / 重置
# --------------------------------------------------------------------------- #
def switch_industry(industry_id: str, role: str = "admin") -> dict[str, Any]:
    _check_role(role, "industry.switch")
    info = _industry(industry_id)
    previous = current_industry()
    store().put("settings", "current", {
        "industry": info["id"], "updatedAt": _now(), "updatedBy": role,
    })
    _log_event("industry.switch", role, info["id"], True, f"{previous} → {info['id']}")
    return {
        "previous": previous,
        "industry": _industry_brief(info),
        "counts": _industry_counts(info["id"]),
        "glossaryCount": len(info.get("glossary", [])),
        "templateCount": len(info.get("workflowTemplates", [])),
        "siteLanguages": [{"code": key, "label": val.get("label", key)} for key, val in info.get("site", {}).items()],
        "crmStages": info.get("crmStages", []),
    }


def get_config(industry_id: str | None = None, role: str = "admin") -> dict[str, Any]:
    ensure_seed()
    role = str(role or "admin")
    if role not in engine_config().get("roles", {}):
        role = "admin"
    industry = _industry(industry_id or current_industry())
    eng = engine_config()
    agent = (industry.get("agents") or [{}])[0]
    permissions = eng.get("permissions", {})
    role_permissions = {
        action: {
            "allowed": role in allowed,
            "label": eng.get("actionLabels", {}).get(action, action),
            "allowedRoles": allowed,
        }
        for action, allowed in permissions.items()
    }
    return {
        "module": "ai",
        "version": eng.get("version", "AI-B.1.0"),
        "engine": eng.get("engine", {}),
        "sampleData": True,
        "disclaimer": "本模块为本地确定性规则引擎（关键词/字符 n-gram 检索 + 意图路由），不调用外部大模型或 API；客户、工坊、价格与站点文案均为合成样例。",
        "roles": eng.get("roles", {}),
        "role": role,
        "roleLabel": eng.get("roles", {}).get(role, role),
        "permissions": role_permissions,
        "actionLabels": eng.get("actionLabels", {}),
        "languages": _languages(),
        "industry": industry["id"],
        "industryName": industry["name"],
        "industryLabel": industry.get("name"),
        "industryBrief": _industry_brief(industry),
        "industries": [_industry_brief(i) for i in industries_config().get("industries", {}).values()],
        "glossary": industry.get("glossary", []),
        "agent": {
            "id": agent.get("id"), "name": agent.get("name"), "tagline": agent.get("tagline"),
            "systemPrompt": agent.get("systemPrompt"), "tools": agent.get("tools", []),
            "starterQuestions": agent.get("starterQuestions", []),
        },
        "workflowTemplates": [_template_public(t) for t in industry.get("workflowTemplates", [])],
        "crmStages": industry.get("crmStages", []),
        "siteLanguages": [
            {"code": key, "label": val.get("label", key), "title": val.get("title")}
            for key, val in industry.get("site", {}).items()
        ],
        "counts": _industry_counts(industry["id"]),
        "limits": eng.get("limits", {}),
        "stepTypeLabels": eng.get("stepTypeLabels", {}),
        "statusLabels": eng.get("statusLabels", {}),
    }


def dashboard(industry_id: str | None = None) -> dict[str, Any]:
    ensure_seed()
    industry = _industry(industry_id or current_industry())
    all_docs = [d for d in store().list("docs", 1000) if d.get("industry") == industry["id"]]
    leads = [lead for lead in store().list("leads", 2000) if lead.get("industry") == industry["id"]]
    workflows = [w for w in store().list("workflows", 500) if w.get("industry") == industry["id"]]
    runs = [r for r in store().list("runs", 1000) if r.get("industry") == industry["id"]]
    sessions = [s for s in store().list("sessions", 1000) if s.get("industry") == industry["id"]]
    success_runs = [r for r in runs if r.get("status") == "success"]
    failed_runs = [r for r in runs if r.get("status") == "failed"]
    total_runs = len(runs)
    success_rate = round(len(success_runs) / total_runs * 100, 1) if total_runs else 0.0
    durations = [int(r.get("durationMs") or 0) for r in success_runs]
    avg_duration = round(sum(durations) / len(durations), 1) if durations else 0.0
    stage_counts: dict[str, int] = {}
    for lead in leads:
        stage_counts[lead.get("stage", "unknown")] = stage_counts.get(lead.get("stage", "unknown"), 0) + 1
    return {
        "industry": industry["id"],
        "industryName": industry["name"],
        "knowledge": {
            "documents": len(all_docs),
            "published": len([d for d in all_docs if d.get("status") == "published"]),
            "drafts": len([d for d in all_docs if d.get("status") == "draft"]),
            "chunks": sum(len(d.get("chunks", [])) for d in all_docs),
        },
        "leads": {
            "total": len(leads),
            "open": len([l for l in leads if l.get("stage") not in ("won", "lost")]),
            "won": len([l for l in leads if l.get("stage") == "won"]),
            "byStage": stage_counts,
        },
        "workflows": {
            "templates": len(industry.get("workflowTemplates", [])),
            "instances": len(workflows),
            "runs": total_runs,
            "success": len(success_runs),
            "failed": len(failed_runs),
            "successRate": success_rate,
            "avgDurationMs": avg_duration,
        },
        "sessions": {
            "total": len(sessions),
            "messages": sum(len(s.get("messages", [])) for s in sessions),
        },
        "siteLanguages": len(_languages()),
        "engine": engine_config().get("engine", {}),
        "sampleData": True,
        "generatedAt": _now(),
    }


def reset_demo(role: str = "admin") -> dict[str, Any]:
    store().reset()
    ensure_seed()
    _log_event("demo.reset", role, "ai", True, "清空 B 模块演示数据并恢复种子知识库")
    return {
        "reset": True,
        "ts": _now(),
        "industry": current_industry(),
        "counts": _industry_counts(current_industry()),
        "message": "B 模块演示数据已清空，种子知识库已恢复（不影响 m2.db）。",
    }

# --------------------------------------------------------------------------- #
# 全链路 scenario
# --------------------------------------------------------------------------- #
def _scenario_doc_payload(role: str) -> dict[str, Any]:
    content = (
        "户外木作推荐使用黑胡桃、白蜡木或柚木。板材含水率应控制在 8%–10%，"
        "沿海高湿环境取 8%，北方干燥环境可放宽至 10%。出厂前必须用含水率仪复测，"
        "并在交付单记录测量点。\n\n"
        "木蜡油采用两底两面，每遍间隔 4–6 小时；完成面 24 小时可轻用，7 天完全固化。"
        "户外家具建议每 6–12 个月补涂一次，雨季前检查榫卯、五金与排水。"
    )
    return write_knowledge({
        "id": "kb-wd-demo-outdoor",
        "title": "户外木作含水率与木蜡油养护（演示文档）",
        "industry": "woodcraft",
        "version": "v1.0",
        "status": "published",
        "source": "页面新建（合成样例）",
        "owner": "运营组（合成）",
        "content": content,
    }, role)


def _scenario_run_brief(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": run["id"], "status": run["status"], "statusLabel": run.get("statusLabel"),
        "attempt": run.get("attempt"), "retryOf": run.get("retryOf"),
        "durationMs": run.get("durationMs"), "leadId": run.get("leadId"),
        "grade": run.get("grade"), "quoteId": run.get("quoteId"),
        "citations": run.get("citations", []),
        "failedStep": run.get("failedStep"),
        "steps": [{
            "index": s.get("index"), "name": s.get("name"), "type": s.get("type"),
            "typeLabel": s.get("typeLabel"), "ok": s.get("ok"), "skipped": s.get("skipped", False),
            "detail": s.get("detail"), "durationMs": s.get("durationMs"),
        } for s in run.get("steps", [])],
    }


def _scenario_search_brief(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "query": result["query"], "count": result["count"],
        "tookMs": result.get("tookMs"),
        "hits": [{
            "citation": h["citation"], "docTitle": h["docTitle"], "score": h["score"],
            "text": h["text"],
        } for h in result["hits"]],
        "suggestions": result.get("suggestions", []),
        "scanned": result.get("scanned"),
    }


def _scenario_message_brief(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "sessionId": result["session"]["id"],
        "intent": result.get("intent"), "intentLabel": result.get("intentLabel"),
        "reply": result.get("reply"),
        "toolCalls": [{
            "tool": c.get("tool"), "ok": c.get("ok"), "args": c.get("args"),
            "resultSummary": c.get("resultSummary"), "durationMs": c.get("durationMs"),
            "leadId": c.get("leadId"), "workflowId": c.get("workflowId"),
        } for c in result.get("toolCalls", [])],
        "citations": [{
            "citation": c.get("citation"), "docTitle": c.get("docTitle"),
            "docVersion": c.get("docVersion"), "score": c.get("score"),
        } for c in result.get("citations", [])],
        "engine": result.get("engine"),
    }


def _scenario_lead_brief(lead: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": lead["id"], "name": lead["name"], "email": lead["email"],
        "country": lead["country"], "countryLabel": lead.get("countryLabel"),
        "interest": lead["interest"], "budgetText": lead.get("budgetText"),
        "stage": lead["stage"], "stageLabel": lead.get("stageLabel"),
        "grade": (lead.get("score") or {}).get("grade"), "source": lead.get("source"),
        "notes": len(lead.get("notes", [])),
    }


def _scenario_site_brief(item: dict[str, Any]) -> dict[str, Any]:
    seo = item["seo"]
    return {
        "lang": item["lang"], "label": item["label"], "title": item["site"]["title"],
        "headline": item["site"]["hero"]["headline"], "faq": len(item["site"].get("faq", [])),
        "seoScore": seo["score"], "coveragePct": seo["coverage"]["pct"],
        "missing": seo["coverage"]["missing"],
    }


def run_scenario(role: str = "admin") -> dict[str, Any]:
    _check_role(role, "scenario.run")
    reset_demo(role)
    steps: list[dict[str, Any]] = []

    def step(title: str, fn, *, expect_error: bool = False):
        try:
            result = fn()
        except AIError as exc:
            steps.append({
                "title": title, "ok": False, "expectError": expect_error,
                "status": exc.status, "error": exc.error, "message": exc.message, "extra": exc.extra,
            })
            return None
        except Exception as exc:  # 场景本身不能把 500 伪装成成功
            steps.append({
                "title": title, "ok": False, "expectError": expect_error,
                "status": 500, "error": "internal_error", "message": str(exc),
            })
            return None
        if expect_error:
            steps.append({
                "title": title, "ok": False, "expectError": True, "status": 200,
                "error": "expected_error_not_raised",
                "message": "预期该步骤失败，但调用成功；请检查校验或权限逻辑。",
            })
            return result
        steps.append({"title": title, "ok": True, "expectError": False, "result": result})
        return result

    industry = step("① 切换行业到 woodcraft（术语/模板/站点全部切换）",
                    lambda: switch_industry("woodcraft", role))
    doc = step("② 新建知识文档（自动切块并写入关键词索引）",
               lambda: _scenario_doc_payload(role))
    doc_id = (doc or {}).get("id", "kb-wd-demo-outdoor")
    doc_brief = {
        "id": doc_id, "title": (doc or {}).get("title"), "version": (doc or {}).get("version"),
        "status": (doc or {}).get("status"), "chunkCount": (doc or {}).get("chunkCount"),
        "chunks": [{"id": c["id"], "text": c["text"], "keywords": c["keywords"]}
                   for c in (doc or {}).get("chunks", [])],
    } if doc else None
    if steps[-1]["ok"]:
        steps[-1]["result"] = doc_brief

    search = step("③ 检索命中：带 score 与 docId#chunk 引用",
                  lambda: search_knowledge("户外餐桌 木蜡油 涂几遍 含水率", "woodcraft", 3, role))
    if search:
        steps[-1]["result"] = _scenario_search_brief(search)

    session = step("④ 智能体首轮：知识检索工具 + 引用",
                   lambda: create_session({"industry": "woodcraft", "title": "木作售前问答（全链路自检）"}, role))
    session_id = (session or {}).get("id", "")
    first = step("⑤ 首轮提问：木蜡油遍数与含水率（本地规则回答）",
                 lambda: _scenario_message_brief(send_session_message(
                     session_id, {"content": "户外餐桌的木蜡油要涂几遍？含水率控制在多少？"}, role)))
    if first:
        first["sessionId"] = session_id

    second = step("⑥ 二轮留资：智能体调用 create_lead 写 CRM",
                  lambda: _scenario_message_brief(send_session_message(
                      session_id,
                      {"content": "另外请登记线索：联系人 周先生，邮箱 zhou@example.com，"
                                  "预算 8 万，想做黑胡桃户外餐桌"},
                      role)))
    agent_lead_id = ""
    if second:
        first_tool = (second.get("toolCalls") or [{}])[0]
        agent_lead_id = first_tool.get("leadId") or ""
        second["sessionId"] = session_id

    inquiry = step("⑦ 询盘表单写入 CRM（邮箱校验通过，阶段 new）",
                   lambda: {
                       **create_inquiry({
                           "name": "林女士", "email": "lin@example.com", "country": "CN",
                           "interest": "白蜡木书柜定制", "budget": "120000",
                           "message": "希望 11 月上门复尺（合成样例）", "lang": "zh",
                       }, "buyer"),
                   })
    inquiry_lead = ((inquiry or {}).get("lead") or {})
    inquiry_lead_id = inquiry_lead.get("id", "")

    updated = step("⑧ CRM 阶段推进：new → contacted 并记备注",
                   lambda: _scenario_lead_brief(update_lead(
                       inquiry_lead_id,
                       {"stage": "contacted", "note": "已电话联系，约本周上门复尺（合成）"},
                       "buyer")))
    if updated:
        updated["history"] = len((store().get("leads", inquiry_lead_id) or {}).get("history", []))

    workflow = step("⑨ 从模板创建木作询盘分诊工作流（7 步）",
                    lambda: {k: v for k, v in create_workflow({
                        "templateId": "wf-wd-inquiry",
                        "name": "木作询盘分诊 · 全链路自检",
                        "industry": "woodcraft",
                    }, role).items() if k in ("id", "name", "templateId", "status", "statusLabel", "createdAt")})
    workflow_id = (workflow or {}).get("id", "")

    run_ok = step("⑩ 工作流成功运行：校验→检索→评级→CRM→报价→通知",
                  lambda: _scenario_run_brief(run_workflow(workflow_id, {"input": {
                      "name": "王先生", "email": "wang@example.com", "country": "CN",
                      "interest": "黑胡桃餐桌 2.2 米", "budget": "200000", "lang": "zh",
                  }}, role)))

    run_fail = step("⑪ 缺邮箱运行失败（校验步骤真实失败，不伪造成功）",
                    lambda: _scenario_run_brief(run_workflow(workflow_id, {"input": {
                        "name": "陈先生", "country": "CN", "interest": "白蜡木书柜",
                        "budget": "60000",
                    }}, role)))
    failed_run_id = (run_fail or {}).get("id", "")

    run_retry = step("⑫ 补齐邮箱后重试成功（attempt 2，retryOf 指向前次失败）",
                     lambda: _scenario_run_brief(retry_run(
                         failed_run_id,
                         {"input": {"email": "chen@example.com", "lang": "zh"}},
                         role)))

    sites = step("⑬ 三语独立站：zh / en / ja 文案与 SEO 同时可读",
                 lambda: [_scenario_site_brief(get_site(lang, "woodcraft"))
                          for lang in ("zh", "en", "ja")])

    seo = step("⑭ SEO 元数据与关键词覆盖检查（确定性匹配）",
               lambda: {
                   "lang": "zh",
                   "score": (get_seo("zh", "woodcraft"))["seo"]["score"],
                   "coverage": (get_seo("zh", "woodcraft"))["seo"]["coverage"],
                   "checks": (get_seo("zh", "woodcraft"))["seo"]["checks"],
               })

    handbook = step("⑮ FDE 驻企交付手册（markdown，可折叠阅读）",
                    lambda: {
                        "title": (lambda h: h["title"])(get_fde_handbook()),
                        "version": (lambda h: h["version"])(get_fde_handbook()),
                        "sections": (lambda h: h["sections"])(get_fde_handbook()),
                        "chars": (lambda h: h["chars"])(get_fde_handbook()),
                        "headings": (lambda h: h["headings"])(get_fde_handbook()),
                    })

    step("⑯ 越权写入知识库被拒（buyer 无 knowledge.write）",
         lambda: write_knowledge({
             "title": "越权测试文档（不应写入）", "industry": "woodcraft",
             "content": "这是一段用于验证权限拒绝的合成文本，长度超过二十个字。",
         }, "buyer"),
         expect_error=True)

    step("⑰ 空检索词返回 400（不返回伪造答案）",
         lambda: search_knowledge("   ", "woodcraft", 3, "buyer"),
         expect_error=True)

    summary = {
        "steps": len(steps),
        "passed": len([s for s in steps if s.get("ok")]),
        "expectedFailures": len([s for s in steps if s.get("expectError") and not s.get("ok")]),
        "industry": "woodcraft",
        "documentId": doc_id,
        "sessionId": session_id,
        "agentLeadId": agent_lead_id,
        "inquiryLeadId": inquiry_lead_id,
        "workflowId": workflow_id,
        "failedRunId": failed_run_id,
        "retriedRunId": (run_retry or {}).get("id"),
        "siteLanguages": ["zh", "en", "ja"],
        "engine": engine_config().get("engine", {}).get("label", "本地规则引擎"),
    }
    return {
        "ok": True,
        "scenario": "ai-full-chain",
        "generatedAt": _now(),
        "steps": steps,
        "summary": summary,
        "dashboard": dashboard("woodcraft"),
        "disclaimer": "全链路在本地同步执行；AI 为规则引擎，不调用外部模型；所有客户与工坊为合成样例。",
    }

# --------------------------------------------------------------------------- #
# HTTP 路由
# --------------------------------------------------------------------------- #
def _handle_error(handler, exc: AIError) -> None:
    body: dict[str, Any] = {"ok": False, "error": exc.error, "message": exc.message}
    for key, value in exc.extra.items():
        body.setdefault(key, value)
    _send(handler, exc.status, body)


def _install_patch_support() -> bool:
    """为 /api/ai/* 增加 PATCH 动词支持（server.py 只实现了 GET/POST）。

    约束要求不改 server.py / extensions.py，因此这里仅给现有 ApiHandler 类补一个
    do_PATCH，把请求转交给本模块的 POST 路由；不影响其他模块的既有路由。
    """
    server = sys.modules.get("server") or sys.modules.get("__main__")
    api_handler = getattr(server, "ApiHandler", None) if server else None
    if api_handler is None or getattr(api_handler, "_ai_patch_ready", False):
        return api_handler is not None

    def do_PATCH(handler):  # noqa: N802 - BaseHTTPRequestHandler 约定
        import extensions

        request_path = urlparse(handler.path).path
        if request_path.startswith("/api/ai/") and extensions.handle(handler, "POST", request_path):
            return
        handler.send_error(404, "Not Found")

    api_handler.do_PATCH = do_PATCH
    api_handler._ai_patch_ready = True
    return True


def _schedule_patch_support() -> None:
    """服务启动后再补 do_PATCH；单元测试没有 server 模块时静默跳过。"""
    timer = threading.Timer(0.4, _install_patch_support)
    timer.daemon = True
    timer.start()


def handle_get(handler, path: str) -> bool:
    if not str(path).startswith("/api/ai/"):
        return False
    _install_patch_support()
    query = _query(handler)
    try:
        if path == "/api/ai/config":
            _send(handler, 200, {"ok": True, **get_config(query.get("industry"), query.get("role") or "admin")})
            return True
        if path == "/api/ai/dashboard":
            _send(handler, 200, {"ok": True, "dashboard": dashboard(query.get("industry"))})
            return True
        if path == "/api/ai/knowledge":
            _send(handler, 200, {"ok": True, **list_knowledge(query.get("industry"), query.get("status"))})
            return True
        if path.startswith("/api/ai/knowledge/"):
            doc_id = unquote(path[len("/api/ai/knowledge/"):]).strip("/")
            if not doc_id:
                raise AIError(404, "doc_not_found", "缺少文档 ID")
            _send(handler, 200, {"ok": True, **get_knowledge(doc_id)})
            return True
        if path.startswith("/api/ai/sessions/"):
            session_id = unquote(path[len("/api/ai/sessions/"):]).strip("/")
            if not session_id:
                raise AIError(404, "session_not_found", "缺少会话 ID")
            _send(handler, 200, {"ok": True, "session": get_session(session_id)})
            return True
        if path == "/api/ai/workflows/runs":
            _send(handler, 200, {"ok": True, **list_runs(
                query.get("workflowId"), query.get("industry"), query.get("limit") or 20)})
            return True
        if path.startswith("/api/ai/workflows/runs/"):
            run_id = unquote(path[len("/api/ai/workflows/runs/"):]).strip("/")
            run = store().get("runs", run_id) if run_id else None
            if not run:
                raise AIError(404, "run_not_found", f"运行记录不存在：{run_id}")
            _send(handler, 200, {"ok": True, "run": run})
            return True
        if path == "/api/ai/workflows":
            _send(handler, 200, {"ok": True, **list_workflows(query.get("industry"))})
            return True
        if path.startswith("/api/ai/workflows/"):
            workflow_id = unquote(path[len("/api/ai/workflows/"):]).strip("/")
            if not workflow_id:
                raise AIError(404, "workflow_not_found", "缺少工作流 ID")
            _send(handler, 200, {"ok": True, "workflow": get_workflow(workflow_id)})
            return True
        if path == "/api/ai/leads":
            _send(handler, 200, {"ok": True, **list_leads(query.get("industry"), query.get("stage"))})
            return True
        if path.startswith("/api/ai/site/"):
            lang = unquote(path[len("/api/ai/site/"):]).strip("/")
            _send(handler, 200, {"ok": True, **get_site(lang, query.get("industry"))})
            return True
        if path == "/api/ai/seo":
            _send(handler, 200, {"ok": True, **get_seo(query.get("lang") or "zh", query.get("industry"))})
            return True
        if path == "/api/ai/fde-handbook":
            _send(handler, 200, {"ok": True, **get_fde_handbook()})
            return True
        if path == "/api/ai/events":
            events = list(reversed(store().list("events", 200)))
            _send(handler, 200, {"ok": True, "events": events, "count": len(events)})
            return True
        _send(handler, 404, {"ok": False, "error": "not_found", "message": f"B 模块无此接口：{path}"})
        return True
    except AIError as exc:
        _handle_error(handler, exc)
        return True
    except Exception as exc:  # pragma: no cover - 防御
        import traceback
        traceback.print_exc()
        _send(handler, 500, {"ok": False, "error": "internal_error", "message": f"服务内部错误：{exc}"})
        return True


def handle_post(handler, path: str) -> bool:
    if not str(path).startswith("/api/ai/"):
        return False
    _install_patch_support()
    try:
        payload = _read_json(handler)
        role = str(payload.get("role") or "admin")
        if path == "/api/ai/industry":
            industry_id = str(payload.get("industry") or "").strip()
            if not industry_id:
                raise AIError(422, "missing_industry", "请选择行业：jewelry / woodcraft")
            _send(handler, 200, {"ok": True, **switch_industry(industry_id, role)})
            return True
        if path == "/api/ai/knowledge":
            _send(handler, 200, {"ok": True, "document": write_knowledge(payload, role)})
            return True
        if path == "/api/ai/search":
            _send(handler, 200, {"ok": True, **search_knowledge(
                payload.get("query"), payload.get("industry"), payload.get("topK"), role)})
            return True
        if path == "/api/ai/sessions":
            _send(handler, 200, {"ok": True, "session": create_session(payload, role)})
            return True
        if path.startswith("/api/ai/sessions/") and path.endswith("/messages"):
            session_id = unquote(path[len("/api/ai/sessions/"):-len("/messages")]).strip("/")
            if not session_id:
                raise AIError(404, "session_not_found", "缺少会话 ID")
            _send(handler, 200, {"ok": True, **send_session_message(session_id, payload, role)})
            return True
        if path == "/api/ai/workflows":
            _send(handler, 200, {"ok": True, "workflow": create_workflow(payload, role)})
            return True
        if path.startswith("/api/ai/workflows/runs/") and path.endswith("/retry"):
            run_id = unquote(path[len("/api/ai/workflows/runs/"):-len("/retry")]).strip("/")
            if not run_id:
                raise AIError(404, "run_not_found", "缺少运行 ID")
            run = retry_run(run_id, payload, role)
            _send(handler, 200, {"ok": True, "run": run, "message": "重试完成，已生成新的运行记录。"})
            return True
        if path.startswith("/api/ai/workflows/") and path.endswith("/run"):
            workflow_id = unquote(path[len("/api/ai/workflows/"):-len("/run")]).strip("/")
            if not workflow_id:
                raise AIError(404, "workflow_not_found", "缺少工作流 ID")
            _send(handler, 200, {"ok": True, "run": run_workflow(workflow_id, payload, role)})
            return True
        if path == "/api/ai/inquiries":
            _send(handler, 200, {"ok": True, **create_inquiry(payload, role)})
            return True
        if path.startswith("/api/ai/leads/"):
            lead_id = unquote(path[len("/api/ai/leads/"):]).strip("/")
            if not lead_id:
                raise AIError(404, "lead_not_found", "缺少线索 ID")
            _send(handler, 200, {"ok": True, "lead": update_lead(lead_id, payload, role)})
            return True
        if path == "/api/ai/scenario":
            _send(handler, 200, run_scenario(role))
            return True
        if path == "/api/ai/demo/reset":
            _check_role(role, "demo.reset")
            _send(handler, 200, {"ok": True, **reset_demo(role)})
            return True
        _send(handler, 404, {"ok": False, "error": "not_found", "message": f"B 模块无此接口：{path}"})
        return True
    except AIError as exc:
        _handle_error(handler, exc)
        return True
    except Exception as exc:  # pragma: no cover - 防御
        import traceback
        traceback.print_exc()
        _send(handler, 500, {"ok": False, "error": "internal_error", "message": f"服务内部错误：{exc}"})
        return True


_schedule_patch_support()




