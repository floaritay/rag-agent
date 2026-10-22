"""重排：硅基流动 /rerank（BAAI/bge-reranker-v2-m3），langchain 压缩器封装。

失败（网络/限流/服务异常）时**抛出异常**，由调用方 search.py 捕获后降级
为 RRF 排序；工厂 make_reranker 是测试 monkeypatch seam（返回 None = 关闭）。
"""

from __future__ import annotations

import httpx
from langchain_core.documents import BaseDocumentCompressor, Document
from pydantic import Field

from ragagent.config import get_settings

_MAX_DOC_CHARS = 4000


class SiliconFlowReranker(BaseDocumentCompressor):
    """按相关性重排 Documents，写入 metadata["relevance_score"]。"""

    top_n: int = Field(default=6)

    def compress_documents(
        self, documents: list[Document], query: str, **kwargs
    ) -> list[Document]:
        docs = list(documents)
        if not docs:
            return []
        s = get_settings()
        r = httpx.post(
            # RERANK_* 覆盖 || 共享；端点需兼容 SiliconFlow /rerank 协议
            f"{s.rerank_base.rstrip('/')}/rerank",
            headers={"Authorization": f"Bearer {s.rerank_key}"},
            json={
                "model": s.rerank_model,
                "query": query,
                # 只截断发送给 API 的负载，不截存储文本
                "documents": [d.page_content[:_MAX_DOC_CHARS] for d in docs],
                "top_n": self.top_n,
            },
            timeout=30,
        )
        if r.status_code != 200:
            raise RuntimeError(f"rerank HTTP {r.status_code}: {r.text[:200]}")
        results = r.json()["results"]
        out: list[Document] = []
        for item in results:
            d = docs[int(item["index"])]
            d.metadata["relevance_score"] = float(item["relevance_score"])
            out.append(d)
        return out


def make_reranker(top_n: int) -> SiliconFlowReranker:
    return SiliconFlowReranker(top_n=top_n)
