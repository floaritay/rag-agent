"""FastAPI 入口。M1：装配知识库管理路由；M2/M3 陆续补对话与 Agent。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ragagent import __version__
from ragagent.config import (
    KNOWLEDGE_BASE_DIR,
    STORAGE_DIR,
    get_settings,
    load_app_config,
)
from ragagent.ingest import bm25_store, chroma_store  # noqa: F401 —— 提前建立存储目录
from ragagent.server.routes_chat import router as chat_router
from ragagent.server.routes_kb import router as kb_router
from ragagent.server.routes_sessions import router as session_router
from ragagent.server.routes_settings import router as settings_router
from ragagent.storage import init_db, upsert_kb


@asynccontextmanager
async def lifespan(_: FastAPI):
    for d in (KNOWLEDGE_BASE_DIR, STORAGE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    init_db()
    # config.yaml 中已注册的知识库同步进 meta.db
    for entry in load_app_config().knowledge_bases:
        upsert_kb(entry.name, entry.path)
    yield


app = FastAPI(title="RAG Agent", version=__version__, lifespan=lifespan)
app.include_router(kb_router)
app.include_router(chat_router)
app.include_router(session_router)
app.include_router(settings_router)


@app.get("/api/health")
def health() -> dict:
    settings = get_settings()
    cfg = load_app_config()
    return {
        "status": "ok",
        "version": __version__,
        "chat_model": settings.chat_model,
        "embed_model": settings.embed_model,
        "rerank_model": settings.rerank_model,
        "key_configured": settings.key_configured,
        "knowledge_bases": [kb.name for kb in cfg.knowledge_bases],
    }


# 前端静态站点（vite build 产物）。挂载在 API 路由之后，不影响 /api/*。
_WEB_DIST = Path(__file__).parent / "web" / "dist"
if _WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_WEB_DIST), html=True), name="web")
