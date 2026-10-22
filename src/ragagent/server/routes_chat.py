"""对话端点：POST /api/chat（SSE），Agent 工具循环。

事件序列：reasoning* / token* / tool* / reset? → citations → done / error。
带 session_id 时：读历史喂给模型，用户/助手消息（含思考过程）落库；
session_id 可选，缺省时不读历史也不落库（无状态）。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ragagent.agent.loop import run_turn
from ragagent.storage import (
    add_message,
    get_kb,
    get_session,
    list_kbs,
    list_messages,
    update_session_kb,
)

router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    kb_id: int | None = None
    message: str
    session_id: int | None = None


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _stream_text(text: str):
    step = 16
    for i in range(0, len(text), step):
        yield {"type": "token", "text": text[i : i + step]}


class _Accumulator:
    """按前端 reducer 规则累积本轮事件，供流结束后落库（镜像 ChatPage 的合并逻辑）。"""

    def __init__(self) -> None:
        self.content = ""
        self.reasoning = ""
        self.tools: list[dict] = []
        self.citations: list | None = None

    def feed(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "reasoning":
            self.reasoning += ev.get("text", "")
        elif t == "token":
            self.content += ev.get("text", "")
        elif t == "tool":
            self.tools.append(ev)
        elif t == "reset":
            self.content = ""
            self.reasoning = ""
            self.tools = []
        elif t == "citations":
            self.citations = ev.get("citations")

    def persist(self, session_id: int | None) -> None:
        """只写 DB、绝不 yield（finally / GeneratorExit 安全）；无实质输出不落库。"""
        if session_id is None:
            return
        if not (self.content or self.reasoning or self.tools or self.citations):
            return
        add_message(
            session_id,
            "assistant",
            self.content,
            tools=self.tools or None,
            citations=self.citations,
            reasoning=self.reasoning or None,
        )


def _generate(body: ChatRequest):
    session_id = body.session_id
    session = get_session(session_id) if session_id is not None else None

    # 知识库解析：请求 > 会话绑定 > 第一个注册库
    kb = None
    if body.kb_id is not None:
        kb = get_kb(body.kb_id)
        if kb is None:
            # 无效请求：不写任何会话行
            yield _sse({"type": "error", "message": f"知识库 {body.kb_id} 不存在"})
            return
        if session is not None and session.kb_id != body.kb_id:
            update_session_kb(session_id, body.kb_id)
    else:
        if session is not None and session.kb_id is not None:
            kb = get_kb(session.kb_id)
        if kb is None:
            # 未指定库时取第一个注册库
            kbs = list_kbs()
            kb = kbs[0] if kbs else None
    default_kb = kb.name if kb is not None else None

    # 历史在前、当前用户消息落库在后（避免把本轮问题读进历史）
    history: list[dict] | None = None
    if session is not None:
        history = [
            {"role": m.role, "content": m.content}
            for m in list_messages(session_id)
        ]
        add_message(session_id, "user", body.message)

    acc = _Accumulator()
    try:
        for ev in _events(body, default_kb, history):
            acc.feed(ev)
            yield _sse(ev)
    except Exception as e:  # noqa: BLE001
        yield _sse({"type": "error", "message": str(e)})
    finally:
        acc.persist(session_id)


def _events(body: ChatRequest, default_kb: str | None, history):
    if default_kb is None:
        yield from _stream_text("还没有可用知识库。请先在管理页创建知识库并入库文档。")
        yield {"type": "done"}
        return

    yield from run_turn(default_kb, body.message, history=history)


@router.post("/chat")
def chat(body: ChatRequest):
    if body.session_id is not None and get_session(body.session_id) is None:
        raise HTTPException(404, f"会话 {body.session_id} 不存在")
    return StreamingResponse(
        _generate(body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
