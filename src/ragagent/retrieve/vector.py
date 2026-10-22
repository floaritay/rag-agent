"""向量检索：langchain-chroma 相似度检索 → 回填 meta.db 生成 Hit。"""

from __future__ import annotations

from ragagent.ingest import chroma_store
from ragagent.storage import get_chunks_by_ids

from .models import Hit, hit_from_row
from .wrappers import ChunkIdEnrichedRetriever


def as_retriever(kb_id: int, k: int) -> ChunkIdEnrichedRetriever | None:
    """构造向量 retriever（k 已按库大小收敛）；空/缺失库返回 None。"""
    count = chroma_store.count(kb_id)
    if count == 0:
        return None
    inner = chroma_store.collection(kb_id).as_retriever(
        search_kwargs={"k": min(k, count)}
    )
    return ChunkIdEnrichedRetriever(inner=inner)


def search(kb_id: int, query: str, k: int) -> list[Hit]:
    retriever = as_retriever(kb_id, k)
    if retriever is None:
        return []
    docs = retriever.invoke(query)
    ids = [int(d.id) for d in docs if d.id is not None]
    rows = get_chunks_by_ids(ids)
    hits: list[Hit] = []
    for cid in ids:
        row = rows.get(cid)
        if row is None:  # 元数据缺失的孤儿向量，跳过
            continue
        # vector 侧分数不外显：融合按 rank，rerank 覆写最终分
        hits.append(hit_from_row(row, score=0.0, source="vector"))
    return hits
