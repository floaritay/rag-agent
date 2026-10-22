"""设置 REST API：/api/settings/models

四类模型（对话/嵌入/重排/图片 OCR）独立读写 + MinerU 密钥/地址 + 图片解析开关；
按服务覆盖写回 .env，运行时回退共享 SILICONFLOW_*。
安全约定：API Key 永不回传全文，仅 key_configured + 掩码。
"""

from __future__ import annotations

import base64
import struct
import zlib

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ragagent.config import Settings, env_path, get_settings, upsert_env_vars
from ragagent.llm import note_vision

router = APIRouter(prefix="/api")

# 类别 → (模型键, 地址键, 密钥键)
_ENV_KEYS = {
    "chat": ("CHAT_MODEL", "CHAT_BASE_URL", "CHAT_API_KEY"),
    "embed": ("EMBED_MODEL", "EMBED_BASE_URL", "EMBED_API_KEY"),
    "rerank": ("RERANK_MODEL", "RERANK_BASE_URL", "RERANK_API_KEY"),
    "ocr": ("OCR_MODEL", "OCR_BASE_URL", "OCR_API_KEY"),
}
_CATEGORIES = ("chat", "embed", "rerank", "ocr")


def _mask(key: str) -> str:
    if not key:
        return ""
    return f"{key[:5]}…{key[-4:]}" if len(key) > 12 else "已配置"


def _cat(s: Settings, model: str, base: str, key: str, configured: bool,
         own_base: bool, own_key: bool) -> dict:
    return {
        "model": model,
        "base_url": base,
        "api_key_masked": _mask(key) if configured else "",
        "key_configured": configured,
        "own_base_url": own_base,
        "own_key": own_key,
    }


def _current() -> dict:
    s = Settings(_env_file=env_path())  # 实时读文件（不走 lru_cache 的 get_settings）
    return {
        "chat": _cat(s, s.chat_model, s.chat_base, s.chat_key, s.chat_key_configured,
                     bool(s.chat_base_url), bool(s.chat_api_key)),
        "embed": _cat(s, s.embed_model, s.embed_base, s.embed_key, s.embed_key_configured,
                      bool(s.embed_base_url), bool(s.embed_api_key)),
        "rerank": _cat(s, s.rerank_model, s.rerank_base, s.rerank_key, s.rerank_key_configured,
                       bool(s.rerank_base_url), bool(s.rerank_api_key)),
        "ocr": _cat(s, s.ocr_model, s.ocr_base, s.ocr_key, s.ocr_key_configured,
                    bool(s.ocr_base_url), bool(s.ocr_api_key)),
        "mineru": {
            "api_key_masked": _mask(s.mineru_api_key) if s.mineru_configured else "",
            "key_configured": s.mineru_configured,
            "base_url": s.mineru_base_url,
        },
        "image_describe": s.image_describe,
    }


class CatUpdate(BaseModel):
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None


class MinerUUpdate(BaseModel):
    api_key: str | None = None
    base_url: str | None = None


class ModelSettings(BaseModel):
    chat: CatUpdate | None = None
    embed: CatUpdate | None = None
    rerank: CatUpdate | None = None
    ocr: CatUpdate | None = None
    mineru: MinerUUpdate | None = None
    image_describe: bool | None = None


def _collect(cat: str, upd: CatUpdate | None, updates: dict[str, str]) -> None:
    if upd is None:
        return
    model_key, base_key, key_key = _ENV_KEYS[cat]
    if upd.model is not None:
        v = upd.model.strip()
        if not v:
            raise HTTPException(422, f"{cat}.model 不能为空")
        updates[model_key] = v
    if upd.base_url is not None:
        v = upd.base_url.strip()
        if not v:
            raise HTTPException(422, f"{cat}.base_url 不能为空")
        if not v.startswith(("http://", "https://")):
            raise HTTPException(422, f"{cat}.base_url 必须以 http:// 或 https:// 开头")
        updates[base_key] = v
    if upd.api_key is not None:
        v = upd.api_key.strip()
        if not v:
            raise HTTPException(422, f"{cat}.api_key 不能为空（留空表示不修改请省略该字段）")
        updates[key_key] = v


@router.get("/settings/models")
def get_model_settings():
    return _current()


@router.put("/settings/models")
def update_model_settings(body: ModelSettings):
    updates: dict[str, str] = {}
    for cat in _CATEGORIES:
        _collect(cat, getattr(body, cat), updates)
    if body.mineru is not None:
        if body.mineru.api_key is not None:
            v = body.mineru.api_key.strip()
            if not v:
                raise HTTPException(422, "mineru.api_key 不能为空（留空表示不修改请省略该字段）")
            updates["MinerU"] = v  # 字面量键名，命中 .env 现有 MinerU= 行
        if body.mineru.base_url is not None:
            v = body.mineru.base_url.strip()
            if not v:
                raise HTTPException(422, "mineru.base_url 不能为空")
            if not v.startswith(("http://", "https://")):
                raise HTTPException(422, "mineru.base_url 必须以 http:// 或 https:// 开头")
            updates["MINERU_BASE_URL"] = v
    if body.image_describe is not None:
        updates["IMAGE_DESCRIBE"] = "true" if body.image_describe else "false"
    if not updates:
        raise HTTPException(422, "没有可更新的字段")

    upsert_env_vars(updates)
    get_settings.cache_clear()  # 下一次聊天/嵌入/重排/OCR 即用新值
    return _current()


def _red_png_b64(size: int = 64) -> str:
    """纯红 PNG（视觉探测用；>28px 满足 DeepSeek-OCR 门槛也兼容）。"""
    def chunk(t: bytes, d: bytes) -> bytes:
        return (struct.pack(">I", len(d)) + t + d
                + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * size for _ in range(size))
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw))
           + chunk(b"IEND", b""))
    return base64.b64encode(png).decode()


@router.post("/settings/models/vision-probe")
def vision_probe():
    """对当前 chat 通道发一张微型测试图，探测模型多模态能力并写入缓存。"""
    s = Settings(_env_file=env_path())
    payload = {
        "model": s.chat_model,
        "max_tokens": 16,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "图是什么颜色？只答颜色词。"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_red_png_b64()}"}},
            ],
        }],
    }
    try:
        r = httpx.post(
            f"{s.chat_base.rstrip('/')}/chat/completions",
            json=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {s.chat_key}"},
            timeout=20,
        )
    except httpx.HTTPError as e:
        raise HTTPException(502, f"探测请求失败：{e}") from e

    if r.status_code == 200:
        note_vision(True)   # 用生效 chat 配置写缓存（与运行时同 key）
        return {"supported": True}
    # 图片类 4xx → 不支持
    from ragagent.llm import _is_image_rejection

    class _Resp(Exception):
        pass

    probe_exc = _Resp(f"status {r.status_code}: {r.text[:300]}")
    probe_exc.status_code = r.status_code  # type: ignore[attr-defined]
    if 400 <= r.status_code < 500 and _is_image_rejection(probe_exc):
        note_vision(False)
        return {"supported": False}
    raise HTTPException(502, f"探测失败 HTTP {r.status_code}: {r.text[:200]}")
