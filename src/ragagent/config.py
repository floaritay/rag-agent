"""配置加载：.env（敏感项，pydantic-settings）+ config.yaml（知识库与参数）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE_DIR = PROJECT_ROOT / "knowledge_base"
STORAGE_DIR = PROJECT_ROOT / "storage"
CHROMA_DIR = STORAGE_DIR / "chroma"
BM25_DIR = STORAGE_DIR / "bm25"
META_DB_PATH = STORAGE_DIR / "meta.db"


class Settings(BaseSettings):
    """敏感项，全部来自 .env。

    共享默认 SILICONFLOW_BASE_URL / SILICONFLOW_API_KEY 适用于全部服务；
    按服务覆盖键（CHAT_*/EMBED_*/RERANK_*）留空即回退共享值——
    既有 .env 原样有效，第三方/多供应商场景可分别配置。
    """

    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    siliconflow_api_key: str = ""
    chat_model: str = "deepseek-ai/DeepSeek-V4-Flash"
    chat_thinking: bool = True  # 思考模式（reasoning_content 流式透出）
    embed_model: str = "BAAI/bge-m3"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    # 按服务覆盖（可选；空 = 回退共享 SILICONFLOW_*）
    chat_base_url: str = ""
    chat_api_key: str = ""
    embed_base_url: str = ""
    embed_api_key: str = ""
    rerank_base_url: str = ""
    rerank_api_key: str = ""

    # 图片通道（DeepSeek-OCR 文字化；独立三件套，绝不复用 chat 通道）
    ocr_model: str = "deepseek-ai/DeepSeek-OCR"  # 需 image-在前 + grounding 提示词（见 ocr.py）
    ocr_base_url: str = ""   # 空 = 回退 SILICONFLOW_BASE_URL
    ocr_api_key: str = ""    # 空 = 回退 SILICONFLOW_API_KEY
    image_describe: bool = True   # env IMAGE_DESCRIBE：A 通道总开关
    image_max_per_doc: int = 20   # env IMAGE_MAX_PER_DOC：单文档图片索引上限（<=0 不限）
    image_attach_max: int = 4     # env IMAGE_ATTACH_MAX：回答时附给对话模型的图片上限（<=0 不限）

    # 扫描件解析通道（MinerU 云；别名覆盖 .env 的字面量 MinerU= 键——必须在 Field 上）
    mineru_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("MinerU", "MINERU_API_KEY", "MINERU_API_TOKEN"),
    )
    mineru_base_url: str = ""   # env MINERU_BASE_URL；空 = SDK 默认云（mineru.net/api/v4）

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @staticmethod
    def _key_ok(key: str) -> bool:
        return bool(key) and "REPLACE" not in key

    @property
    def key_configured(self) -> bool:
        return self._key_ok(self.siliconflow_api_key)

    # —— 生效值（按服务覆盖 || 共享）——
    @property
    def chat_base(self) -> str:
        return self.chat_base_url or self.siliconflow_base_url

    @property
    def chat_key(self) -> str:
        return self.chat_api_key or self.siliconflow_api_key

    @property
    def chat_key_configured(self) -> bool:
        return self._key_ok(self.chat_key)

    @property
    def embed_base(self) -> str:
        return self.embed_base_url or self.siliconflow_base_url

    @property
    def embed_key(self) -> str:
        return self.embed_api_key or self.siliconflow_api_key

    @property
    def embed_key_configured(self) -> bool:
        return self._key_ok(self.embed_key)

    @property
    def rerank_base(self) -> str:
        return self.rerank_base_url or self.siliconflow_base_url

    @property
    def rerank_key(self) -> str:
        return self.rerank_api_key or self.siliconflow_api_key

    @property
    def rerank_key_configured(self) -> bool:
        return self._key_ok(self.rerank_key)

    # —— 图片 OCR 通道（回退共享）——
    @property
    def ocr_base(self) -> str:
        return self.ocr_base_url or self.siliconflow_base_url

    @property
    def ocr_key(self) -> str:
        return self.ocr_api_key or self.siliconflow_api_key

    @property
    def ocr_key_configured(self) -> bool:
        return self._key_ok(self.ocr_key)

    @property
    def mineru_configured(self) -> bool:
        return self._key_ok(self.mineru_api_key)


@dataclass
class KBEntry:
    name: str
    path: str


@dataclass
class ChunkingConfig:
    chunk_size: int = 500
    overlap: int = 80


@dataclass
class RetrievalConfig:
    vector_k: int = 8
    bm25_k: int = 8
    rrf_k: int = 60
    top_n: int = 6
    rerank_enabled: bool = True


@dataclass
class AppConfig:
    knowledge_bases: list[KBEntry] = field(default_factory=list)
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)


def load_app_config(path: Path | None = None) -> AppConfig:
    p = path or PROJECT_ROOT / "config.yaml"
    data: dict = {}
    if p.exists():
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    kbs = []
    for kb in data.get("knowledge_bases", []) or []:
        unknown = set(kb) - {"name", "path"}
        if unknown:
            raise ValueError(f"config.yaml 知识库存在未知字段 {unknown}：{kb}")
        if "name" not in kb or "path" not in kb:
            raise ValueError(f"config.yaml 知识库缺少 name/path：{kb}")
        kbs.append(KBEntry(**kb))

    return AppConfig(
        knowledge_bases=kbs,
        chunking=ChunkingConfig(**(data.get("chunking") or {})),
        retrieval=RetrievalConfig(**(data.get("retrieval") or {})),
    )


def save_app_config(cfg: AppConfig, path: Path | None = None) -> None:
    """回写 config.yaml（管理 API 注册/注销知识库时调用；注释会丢失）。"""
    import dataclasses

    p = path or PROJECT_ROOT / "config.yaml"
    data = {
        "knowledge_bases": [
            {"name": kb.name, "path": kb.path}
            for kb in cfg.knowledge_bases
        ],
        "chunking": dataclasses.asdict(cfg.chunking),
        "retrieval": dataclasses.asdict(cfg.retrieval),
    }
    p.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def env_path() -> Path:
    """.env 路径——调用时读 PROJECT_ROOT（测试可 monkeypatch 隔离）。"""
    return PROJECT_ROOT / ".env"


def upsert_env_vars(updates: dict[str, str]) -> None:
    """只替换/追加传入的键，其余行原样保留（.env 是敏感文件，勿整写）。"""
    if not updates:
        return
    p = env_path()
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    for key, value in updates.items():
        pat = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
        if pat.search(text):
            text = pat.sub(f"{key}={value}", text, count=1)
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += f"{key}={value}\n"
    if not text.endswith("\n"):
        text += "\n"
    p.write_text(text, encoding="utf-8", newline="")


@lru_cache
def get_settings() -> Settings:
    return Settings()
