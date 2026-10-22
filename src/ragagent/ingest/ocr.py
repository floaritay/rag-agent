"""图片文字化与说明客户端。

两个能力：
1. `describe_image` —— 逐字 OCR：默认 deepseek-ai/DeepSeek-OCR 官方 grounding 形态
   —— **image_url 块必须放在 text 块之前** + 提示词
   `<image>\\n<|grounding|>OCR this image.`，模型才会进入 OCR 模式
   （输出 `<|ref|>文字<|/ref|><|det|>[[坐标]]<|/det|>`）；文字在前会输出幻觉乱码。
   输出用 `_extract_grounding` 抽取 ref 片段。其他视觉模型走通用分支（文字在前+中文指令）。
2. `describe_picture` —— 看图一句说明（图表主题/关键元素）：OCR 只会得到「a b」这类
   符号碎片（如余弦相似度示意图），语义必须由视觉模型补；走**对话通道**的多模态能力
   （chat_base/chat_key），纯文本对话模型或失败时返回 None 静默退化。

OCR 通道独立（OCR_BASE_URL/OCR_API_KEY 回退共享 SILICONFLOW_*），绝不拿 chat 通道做 OCR。
契约：任何失败返回 None，绝不抛出——单图失败不 fail 文档。
"""

from __future__ import annotations

import base64
import io
import re

import httpx

from ragagent.config import get_settings
from ragagent.llm import _is_image_rejection, note_vision, vision_supported

# DeepSeek-OCR 原生 grounding 提示词（配合 image-在前 的 content 顺序）
_DEEPSEEK_OCR_PROMPT = "<image>\n<|grounding|>OCR this image."

# 通用视觉模型提示词（Qwen-VL 等）
DEFAULT_PROMPT = (
    "提取图片中的全部文字，保持阅读顺序，表格转成 Markdown。\n"
    "若为图表/示意图，另起一行以「摘要：」给出一句话结论。\n"
    "图片无文字时只输出「摘要：」一句话。不要编造图中不存在的内容。"
)

_MIN_PX = 28          # 部分 OCR 模型要求边长 >28（DeepSeek-OCR 小于此值会报 400）
_SAFE_PX = 64         # 过小图放大目标
_TIMEOUT = 90.0
_MIME = {
    "png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg",
    "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp",
}


def _prepare_bytes(data: bytes, ext: str) -> bytes:
    """过小图放大（只影响送 OCR 的副本，不改落盘字节）。"""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            if min(im.size) <= _MIN_PX:
                scale = max(1, -(-_SAFE_PX // max(min(im.size), 1)))
                im = im.resize((im.width * scale, im.height * scale))
                buf = io.BytesIO()
                fmt = "PNG" if ext == "png" else "JPEG"
                im.convert("RGB").save(buf, format=fmt)
                return buf.getvalue()
    except Exception:  # noqa: BLE001 —— PIL 打不开（EMF/WMF 等）就用原字节试
        pass
    return data


_GROUNDING_TOKEN_RE = re.compile(r"<\|[^|]*\|>")          # <|ref|> 等模型特殊标记（含孤立）
_STRAY_TAG_RE = re.compile(r"</?[a-zA-Z][a-zA-Z0-9]{0,9}>")  # </td> 等输出噪声标签


def _clean_span(text: str) -> str:
    """单段识别文本清洗：剥模型标记与噪声标签（ref 片段内也可能混入）。"""
    text = _GROUNDING_TOKEN_RE.sub("", text)
    text = _STRAY_TAG_RE.sub("", text)
    return text.strip()


def _extract_grounding(content: str) -> str | None:
    """DeepSeek-OCR 输出 → 纯文本：抽 <|ref|>…<|/ref|> 片段（逐段清洗）；无 ref 整体清洗。"""
    content = (content or "").strip()
    if not content:
        return None
    refs = re.findall(r"<\|ref\|>(.*?)<\|/ref\|>", content, re.S)
    if refs:
        return "\n".join(t for t in (_clean_span(r) for r in refs) if t) or None
    return _clean_span(content) or None


def _sanitize_ocr_text(text: str) -> str | None:
    """质量门：截断小模型复读循环（任一 12 字窗口出现第 3 次 → 截到第 2 次前）。"""
    text = (text or "").strip()
    if not text:
        return None
    win = 12
    first_seen: dict[str, int] = {}
    second_seen: dict[str, int] = {}
    for i in range(max(0, len(text) - win + 1)):
        w = text[i : i + win]
        if w in second_seen:
            return text[: second_seen[w]].strip() or None
        if w in first_seen:
            second_seen[w] = i
        else:
            first_seen[w] = i
    return text


def describe_image(data: bytes, ext: str) -> str | None:
    """图片 → 文本（OCR + 图表摘要）。失败返回 None。"""
    s = get_settings()
    if not s.ocr_key_configured:
        return None
    raw = _prepare_bytes(data, ext)
    b64 = base64.b64encode(raw).decode()

    deepseek = "deepseek-ocr" in (s.ocr_model or "").lower()
    if deepseek:
        # 官方调用形态：image 块在前 + grounding 提示词（顺序颠倒会输出幻觉乱码）；
        # MIME 按社区脚本写 application/pdf（对 png/jpg 同样有效）
        content = [
            {"type": "image_url", "image_url": {"url": f"data:application/pdf;base64,{b64}"}},
            {"type": "text", "text": _DEEPSEEK_OCR_PROMPT},
        ]
    else:
        mime = _MIME.get(ext, "image/png")
        content = [
            {"type": "text", "text": DEFAULT_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ]
    payload = {
        "model": s.ocr_model,
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": content}],
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {s.ocr_key}"}
    endpoint = f"{s.ocr_base.rstrip('/')}/chat/completions"
    for attempt in range(2):  # 超时/5xx 重试 1 次；4xx 不重试
        try:
            r = httpx.post(endpoint, json=payload, headers=headers, timeout=_TIMEOUT)
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt == 0:
                continue
            return None
        if r.status_code == 200:
            try:
                text = (r.json()["choices"][0]["message"].get("content") or "").strip()
            except (KeyError, IndexError, ValueError):
                return None
            if deepseek:
                text = _extract_grounding(text)
            return _sanitize_ocr_text(text)
        if r.status_code >= 500 and attempt == 0:
            continue
        return None  # 4xx 等：key/额度/格式问题，不重试
    return None


_DESCRIBE_PROMPT = (
    "用一两句话说明这张图：如果是图表/示意图，说明主题、关键元素与结论"
    "（如坐标轴含义、公式含义、流程走向）；如果只是文字截图，概括其内容。"
    "只输出说明本身，不要开场白。"
)
_DESCRIBE_MAX_TOKENS = 200


def describe_picture(data: bytes, ext: str) -> str | None:
    """看图出一句语义说明（OCR 的「a b」碎片靠它补足含义）。失败返回 None。

    走对话通道（chat_base/chat_key，已验证多模态）；能力缓存为 False 或
    图片类 4xx 拒绝时静默退化（并同步 VISION_CAPABILITY，供回答附原图复用）。
    """
    s = get_settings()
    if not s.chat_key_configured or not vision_supported():
        return None
    raw = _prepare_bytes(data, ext)
    b64 = base64.b64encode(raw).decode()
    mime = _MIME.get(ext, "image/png")
    payload = {
        "model": s.chat_model,
        "max_tokens": _DESCRIBE_MAX_TOKENS,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": _DESCRIBE_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }],
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {s.chat_key}"}
    endpoint = f"{s.chat_base.rstrip('/')}/chat/completions"
    try:
        r = httpx.post(endpoint, json=payload, headers=headers, timeout=_TIMEOUT)
    except (httpx.TimeoutException, httpx.TransportError):
        return None
    if r.status_code != 200:
        class _Resp(Exception):
            pass

        exc = _Resp(f"status {r.status_code}: {r.text[:200]}")
        exc.status_code = r.status_code  # type: ignore[attr-defined]
        if 400 <= r.status_code < 500 and _is_image_rejection(exc):
            note_vision(False)  # 与回答附原图共享能力缓存：该模型不支持看图
        return None
    try:
        text = (r.json()["choices"][0]["message"].get("content") or "").strip()
    except (KeyError, IndexError, ValueError):
        return None
    return _sanitize_ocr_text(text)
