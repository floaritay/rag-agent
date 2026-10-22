"""检索编排：向量 + BM25 → langchain EnsembleRetriever（RRF 融合）→
重排（可开关，失败降级）。

等权重 + c=rrf_k + 按 chunk_id 去重，与原自研 fusion.rrf 排序同构。
"""

from __future__ import annotations

from langchain_classic.retrievers import EnsembleRetriever
from langchain_core.documents import Document

from ragagent.config import load_app_config
from ragagent.storage import get_chunks_by_ids

from . import bm25, rerank, vector
from .models import Hit, hit_from_row


def _hydrate(docs: list[Document], rrf_k: int) -> list[Hit]:
    """融合结果 → Hit（回填 meta.db；孤儿跳过；RRF 分按名次合成）。"""
    rows = get_chunks_by_ids([int(d.id) for d in docs if d.id is not None])
    hits: list[Hit] = []
    rank = 0
    for d in docs:
        if d.id is None:
            continue
        row = rows.get(int(d.id))
        if row is None:
            continue
        rank += 1
        hits.append(hit_from_row(row, score=1.0 / (rrf_k + rank), source="rrf"))
    return hits


def search(kb_id: int, query: str) -> list[Hit]:
    """返回精排后的 top_n 命中，供对话引用与 search_kb 工具使用。"""
    conf = load_app_config().retrieval
    retrievers = [
        r
        for r in (
            vector.as_retriever(kb_id, conf.vector_k),
            bm25.as_retriever(kb_id, conf.bm25_k),
        )
        if r is not None
    ]
    if not retrievers:
        return []
    fused_docs = EnsembleRetriever(
        retrievers=retrievers,  # 默认等权重
        c=conf.rrf_k,
        id_key="chunk_id",
    ).invoke(query)
    if not fused_docs:
        return []
    hits = _hydrate(fused_docs, conf.rrf_k)
    if not hits:
        return []
    if conf.rerank_enabled:
        rdocs: list[Document] | None = None
        try:
            compressor = rerank.make_reranker(conf.top_n)
            if compressor is None:
                raise RuntimeError("重排工厂返回 None")
            rdocs = compressor.compress_documents(
                [
                    Document(page_content=h.text, metadata={"chunk_id": h.chunk_id})
                    for h in hits
                ],
                query,
            )
        except Exception:  # noqa: BLE001 —— 任何异常一律降级为 RRF 序
            rdocs = None
        if rdocs is not None:
            by_cid = {h.chunk_id: h for h in hits}
            out: list[Hit] = []
            for d in rdocs:
                h = by_cid.get(int(d.metadata["chunk_id"]))
                if h is None:
                    continue
                h.score = float(d.metadata.get("relevance_score", 0.0))
                h.source = "rerank"
                out.append(h)
            return out
    return hits[: conf.top_n]
