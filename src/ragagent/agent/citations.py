"""引用白名单：答案中的引用必须来自本轮工具返回的片段，违规触发重生成。"""

from __future__ import annotations

import re

from ragagent.retrieve.models import Hit

_CITE_RE = re.compile(r"\[来源:\s*([^\],\]]+)\s*,\s*([^\]]+)\]")


def extract_citations(answer: str) -> list[tuple[str, str, str]]:
    """返回 [(引用原文, 路径, 位置)]。"""
    out = []
    for m in _CITE_RE.finditer(answer):
        out.append((m.group(0), m.group(1).strip(), m.group(2).strip()))
    return out


def _norm(s: str) -> str:
    return s.strip().strip("。").replace("\\", "/").strip("/").lower()


def _path_matches(cite_path: str, h: Hit, kb_names: set[str]) -> bool:
    c = _norm(cite_path)
    rel = _norm(h.rel_path)
    if c == rel or c.endswith("/" + rel):
        return True
    # 模型可能带库名前缀（含中文/大小写差异），剥离已知库名前缀后再比对
    for name in kb_names:
        prefix = _norm(name) + "/"
        if c.startswith(prefix) and c[len(prefix):] == rel:
            return True
    return False


def _loc_matches(cite_loc: str, h: Hit) -> bool:
    if h.source == "list_sources":
        return True  # 文档清单条目没有正文位置，路径匹配即可
    loc = cite_loc.strip()
    for part in re.split(r"[，,;；]", loc):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^p\.?\s*(\d+)$", part, re.IGNORECASE)
        if m:
            if h.page is not None and int(m.group(1)) == h.page:
                return True
        else:
            hp = h.heading_path.lower()
            if part and part.lower() in hp:
                return True
    return False


def validate_citations(answer: str, hits, kb_names: set[str] | None = None) -> list[str]:
    """返回违规引用原文列表（路径或位置对不上任何命中片段）。"""
    hit_list = list(hits)
    kb_names = kb_names or set()
    violations = []
    for raw, path, loc in extract_citations(answer):
        ok = any(
            _path_matches(path, h, kb_names) and _loc_matches(loc, h)
            for h in hit_list
        )
        if not ok:
            violations.append(raw)
    return violations


def citation_of(h: Hit, index: int) -> dict:
    out = {
        "index": index,
        "chunk_id": h.chunk_id,
        "rel_path": h.rel_path,
        "type": h.type,
        "heading_path": h.heading_path,
        "page": h.page,
        "location": h.location,
        "score": round(h.score, 4),
        "snippet": h.text[:120],
    }
    if h.image_path:  # additive：前端可据此渲染缩略图（v1 暂不服务图片字节）
        out["image_path"] = h.image_path
    return out
