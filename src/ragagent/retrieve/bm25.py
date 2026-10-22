"""BM25 检索：langchain BM25Retriever（过滤式）+ 每库 pickle 索引。"""

from __future__ import annotations

from ragagent.ingest.bm25_store import _tokens, load
from ragagent.storage import get_chunks_by_ids

from .models import Hit, hit_from_row
from .wrappers import ChunkIdEnrichedRetriever


def as_retriever(kb_id: int, k: int) -> ChunkIdEnrichedRetriever | None:
    """构造带 chunk_id 回填的 BM25 retriever；无索引返回 None。"""
    data = load(kb_id)
    if data is None:
        return None
    # chunk_id metadata 在重建时已写入；包装层幂等兜底
    return ChunkIdEnrichedRetriever(inner=data.model_copy(update={"k": k}))


def search(kb_id: int, query: str, k: int) -> list[Hit]:
    data = load(kb_id)
    if data is None:
        return []
    scores = data.vectorizer.get_scores(_tokens(query))
    pairs = [
        (i, float(s))
        for i, s in enumerate(scores)
        if s > 0
    ]
    pairs.sort(key=lambda p: p[1], reverse=True)
    pairs = pairs[:k]
    ids = [int(data.docs[i].id) for i, _ in pairs]
    rows = get_chunks_by_ids(ids)
    hits: list[Hit] = []
    for (i, s), cid in zip(pairs, ids):
        row = rows.get(cid)
        if row is None:
            continue
        hits.append(hit_from_row(row, score=s, source="bm25"))
    return hits
