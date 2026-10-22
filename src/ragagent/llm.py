"""对话模型工厂：硅基流动 ChatOpenAI + function-calling 工具绑定。

生产侧在工厂内完成 bind_tools——测试通过 monkeypatch
`agent.loop.make_chat_model` 返回 FakeMessagesListChatModel
（其 bind_tools 会抛 NotImplementedError，因此绑定必须在工厂里做）。

思考模式：`thinking={"type": "enabled"}` 让模型流式输出 reasoning_content；
langchain-openai 1.x 明确不提取该字段（官方建议 provider 子类），
故 ThinkingChatOpenAI 把它挂进 chunk.additional_kwargs，供 loop 转发为
reasoning 事件。
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from ragagent.agent.tools import TOOLS_SCHEMA
from ragagent.config import get_settings

# —— 多模态能力缓存（回答附原图）：按 (base_url, model) 记录，进程内存态 ——
# 缺省乐观 True；仅在「本轮确实附了图 + 收到图片类 4xx 拒绝」时写 False。
VISION_CAPABILITY: dict[tuple[str, str], bool] = {}

_VISION_REJECT_KEYWORDS = (
    "image", "vision", "content type", "content_type", "multimodal",
    "unsupported", "invalid content", "不支持",
)


def vision_capability_key() -> tuple[str, str]:
    s = get_settings()
    return (s.chat_base, s.chat_model)


def vision_supported() -> bool:
    return VISION_CAPABILITY.get(vision_capability_key(), True)


def note_vision(ok: bool) -> None:
    VISION_CAPABILITY[vision_capability_key()] = ok


def _is_image_rejection(exc: Exception) -> bool:
    """是否为「模型不支持图片输入」类拒绝：4xx + 关键词；无 status 仅按关键词。"""
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    if status is not None and not (400 <= int(status) < 500):
        return False
    msg = str(exc).lower()
    return any(k in msg for k in _VISION_REJECT_KEYWORDS)


class ThinkingChatOpenAI(ChatOpenAI):
    """透传 reasoning_content → additional_kwargs["reasoning_content"]。"""

    def _convert_chunk_to_generation_chunk(
        self, chunk: dict, default_chunk_class, base_generation_info
    ):
        gen = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if gen is not None:
            choices = chunk.get("choices") or []
            delta = (choices[0].get("delta") or {}) if choices else {}
            rsn = delta.get("reasoning_content")
            if rsn:
                gen.message.additional_kwargs["reasoning_content"] = rsn
        return gen


def make_chat_model():
    """返回**已绑定工具**的对话模型（Runnable），供 agent 节点 stream/invoke。"""
    s = get_settings()
    kwargs: dict = {}
    if s.chat_thinking:
        kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
    llm = ThinkingChatOpenAI(
        model=s.chat_model,
        api_key=s.chat_key,      # CHAT_API_KEY || SILICONFLOW_API_KEY
        base_url=s.chat_base,    # CHAT_BASE_URL || SILICONFLOW_BASE_URL
        temperature=0.3,
        max_retries=1,
        timeout=120,
        **kwargs,
    )
    return llm.bind_tools(TOOLS_SCHEMA)


def make_subagent_model(tools_schema: list | None = None):
    """子代理模型工厂：与主模型同配置；schema 为 None 时不绑工具（general 型）。"""
    s = get_settings()
    kwargs: dict = {}
    if s.chat_thinking:
        kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
    llm = ThinkingChatOpenAI(
        model=s.chat_model,
        api_key=s.chat_key,
        base_url=s.chat_base,
        temperature=0.3,
        max_retries=1,
        timeout=120,
        **kwargs,
    )
    return llm.bind_tools(tools_schema) if tools_schema else llm
