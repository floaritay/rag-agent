"""嵌入工厂：硅基流动 OpenAI 兼容接口（bge-m3，1024 维）。

叶子模块：只依赖 config 与 langchain_openai，供 chroma_store 等低层模块
安全 import（不可反向依赖 llm.py，否则成环）。
"""

from __future__ import annotations

from langchain_openai import OpenAIEmbeddings

from ragagent.config import get_settings


def make_embeddings() -> OpenAIEmbeddings:
    s = get_settings()
    return OpenAIEmbeddings(
        model=s.embed_model,
        api_key=s.embed_key,      # EMBED_API_KEY || SILICONFLOW_API_KEY
        base_url=s.embed_base,    # EMBED_BASE_URL || SILICONFLOW_BASE_URL
        chunk_size=32,  # 每批 32 条，嵌入调用有界
        max_retries=3,
        request_timeout=60,
    )
