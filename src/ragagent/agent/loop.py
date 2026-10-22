"""Agent 工具循环：LangGraph StateGraph，≤8 轮 function-calling。

事件流：reasoning*（思考过程）/ token*（流式回答）/ tool（工具调用摘要）→
reset（重生成前清空）→ citations（白名单内的引用清单）→ done / error。

- token/tool 由节点内 `get_stream_writer` 实时写入（stream_mode="custom"，
  节点运行中即送达前端）；
- 引用白名单校验与仅一次重生成由 run_turn 在图外编排（同 config 二次
  pass，靠 MemorySaver 续状态）；
- `make_chat_model` 是测试 seam：monkeypatch 本模块同名属性返回
  FakeMessagesListChatModel 脚本。
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Annotated, Iterator, TypedDict
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

import ragagent.config as cfg
from ragagent.agent.citations import citation_of, validate_citations
from ragagent.agent.memory import maybe_trigger_maintenance
from ragagent.agent.prompts import build_system_prompt
from ragagent.agent.tools import execute_tool
from ragagent.llm import (
    _is_image_rejection,
    make_chat_model,
    note_vision,
    vision_supported,
)
from ragagent.retrieve.models import Hit
from ragagent.storage import list_kbs

MAX_ROUNDS = 8
HISTORY_MAX_MESSAGES = 12  # 喂给模型的历史条数上限（DB 保留全量）

# 回答期附图参数（张数以 .env 的 IMAGE_ATTACH_MAX 为准，<=0 不限）
MAX_ATTACH_IMAGES = 4
_MAX_ATTACH_PX = 1280
_ATTACH_JPEG_Q = 80

_REGEN_PROMPT = (
    "（系统内部指令，非用户消息，用户看不到本条）\n"
    "自动引用校验未通过：上一条回答中以下来源不在本轮检索结果中：\n{violations}\n"
    "请仅依据本轮工具返回的片段重新输出完整回答；引用格式 "
    "[来源: <库名>/<路径>, <位置>]；若无相关片段请明确说明没有相关记录。"
    "直接输出回答本身：不要解释校验过程，不要说“您指出的/重新整理/上一条回答”，"
    "不要以说明性前言开头。"
)


class _State(TypedDict):
    messages: Annotated[list, add_messages]
    rounds: int  # 已发生的 LLM 轮数


def _content_text(content) -> str:
    """AIMessage.content → 纯文本（str / content-block 列表 / None）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict) and p.get("text"):
                parts.append(str(p["text"]))
        return "".join(parts)
    return "" if content is None else str(content)


def _collect_attach_paths(registry: dict[int, Hit]) -> list[str]:
    """本轮命中中带图片的片段：score 降序去重，≤ IMAGE_ATTACH_MAX（<=0 不限）。"""
    cap = cfg.get_settings().image_attach_max
    hits = [h for h in registry.values() if h.image_path]
    hits.sort(key=lambda h: h.score, reverse=True)
    out: list[str] = []
    seen: set[str] = set()
    for h in hits:
        if h.image_path in seen:
            continue
        seen.add(h.image_path)
        out.append(h.image_path)
        if cap > 0 and len(out) >= cap:
            break
    return out


def _image_data_url(rel: str) -> str | None:
    """storage 相对路径 → JPEG data URL（alpha 白底、>1280 缩放、GIF 首帧）。失败 None。"""
    try:
        from PIL import Image

        p = cfg.STORAGE_DIR / Path(rel)
        with Image.open(p) as im:
            if getattr(im, "format", None) == "GIF":
                im.seek(0)
            if im.mode in ("RGBA", "LA", "P"):
                rgba = im.convert("RGBA")
                bg = Image.new("RGB", rgba.size, (255, 255, 255))
                bg.paste(rgba, mask=rgba.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
            if max(im.size) > _MAX_ATTACH_PX:
                im.thumbnail((_MAX_ATTACH_PX, _MAX_ATTACH_PX))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=_ATTACH_JPEG_Q)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/jpeg;base64,{b64}"
    except Exception:  # noqa: BLE001 —— 单图失败跳过，不影响其他图
        return None


def _attach_images(msgs: list, paths: list[str]) -> list | None:
    """消息拷贝：最后一条 HumanMessage → [text 块, image_url 块…]；不改原消息/state。"""
    parts: list[dict] = []
    for rel in paths:
        url = _image_data_url(rel)
        if url:
            parts.append({"type": "image_url", "image_url": {"url": url}})
    if not parts:
        return None
    out = list(msgs)
    for i in range(len(out) - 1, -1, -1):
        m = out[i]
        if isinstance(m, HumanMessage):
            text = _content_text(m.content)
            if not text:
                return None
            out[i] = HumanMessage(
                content=[{"type": "text", "text": text}, *parts],
                id=m.id,
            )
            return out
    return None


def _stream_once(model, msgs: list, writer) -> tuple:
    """跑一遍流并转发 reasoning/token 事件，返回 (acc, 是否发出过事件)。"""
    acc = None
    emitted = False
    for chunk in model.stream(msgs):
        # 思考模式：reasoning_content 在 additional_kwargs（不进 content，
        # 不回喂历史、不参与引用校验）
        rsn = (getattr(chunk, "additional_kwargs", None) or {}).get("reasoning_content")
        if rsn:
            writer({"type": "reasoning", "text": rsn})
            emitted = True
        text = _content_text(getattr(chunk, "content", None))
        if text:
            writer({"type": "token", "text": text})
            emitted = True
        acc = chunk if acc is None else acc + chunk
    return acc, emitted


def _build_graph(default_kb: str | None, registry: dict[int, Hit], checkpointer):
    def agent_node(state: _State) -> dict:
        model = make_chat_model()  # 测试 monkeypatch seam（loop 命名空间）
        writer = get_stream_writer()
        # 标准归约：chunk + chunk 才能按 index 合并同一 tool_call 的分片 delta
        # （DeepSeek 流式会拆成 {name,id,args:''} + {name:'',args:'…'} 两段，
        # 拼原始列表重解析会裂成两个调用并截断 args）。
        # 命中图片片段且视觉能力未知/为真 → 附原图（只改 stream 的消息拷贝）
        msgs = state["messages"]
        attached = False
        emitted = False  # 先绑定：首次 _stream_once 抛异常时 except 也要能读
        if vision_supported():
            paths = _collect_attach_paths(registry)
            if paths:
                att = _attach_images(msgs, paths)
                if att is not None:
                    msgs = att
                    attached = True
        try:
            acc, emitted = _stream_once(model, msgs, writer)
        except Exception as e:  # noqa: BLE001
            # 图片类拒绝且尚未发出任何事件 → 标记不支持并本轮无图重试一次
            if attached and not emitted and _is_image_rejection(e):
                note_vision(False)
                acc, _ = _stream_once(model, state["messages"], writer)
            else:
                raise
        else:
            if attached:
                note_vision(True)

        tool_calls = list(getattr(acc, "tool_calls", None) or []) if acc is not None else []
        # tool_call id 规范化，与 tools_node 的 ToolMessage.tool_call_id 对齐
        tool_calls = [
            {**tc, "id": tc.get("id") or f"call_{i}"}
            for i, tc in enumerate(tool_calls)
        ]
        content = _content_text(getattr(acc, "content", None)) if acc is not None else ""
        return {
            "messages": [AIMessage(content=content, tool_calls=tool_calls)],
            "rounds": state.get("rounds", 0) + 1,
        }

    def tools_node(state: _State) -> dict:
        writer = get_stream_writer()
        last = state["messages"][-1]
        out: list[ToolMessage] = []
        for i, tc in enumerate(last.tool_calls or []):
            args = tc.get("args") or {}
            arguments = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
            result, summary = execute_tool(tc["name"], arguments, default_kb, registry)
            writer({"type": "tool", "name": tc["name"], "summary": summary})
            # 数据/指令分离：所有工具结果（含检索原文）包进 <tool_output> 标签，
            # 与 system/user 指令通道结构隔离（提示词安全边界条款配合生效）
            out.append(
                ToolMessage(
                    content=f'<tool_output name="{tc["name"]}">\n{result}\n</tool_output>',
                    tool_call_id=tc.get("id") or f"call_{i}",
                )
            )
        return {"messages": out}

    def route(state: _State) -> str:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            # 触达轮次上限：直接结束（run_turn 检测末条带 tool_calls → 报错）
            if state.get("rounds", 0) >= MAX_ROUNDS:
                return END
            return "tools"
        return END

    g = StateGraph(_State)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile(checkpointer=checkpointer)


def _pass(graph, inputs: dict, config: dict) -> Iterator[dict]:
    """跑一遍图，原样转发节点写入的 custom 事件（token/tool）。"""
    yield from graph.stream(inputs, config, stream_mode="custom")


def _text_of(msg) -> str:
    return _content_text(getattr(msg, "content", None))


def _history_messages(history: list[dict] | None) -> list:
    """历史 [{"role","content"}] → LangChain 消息；截断后不以 assistant 开头。"""
    if not history:
        return []
    capped = history[-HISTORY_MAX_MESSAGES:]
    while capped and capped[0].get("role") != "user":
        capped = capped[1:]
    out = []
    for m in capped:
        if m.get("role") == "user":
            out.append(HumanMessage(f"<user_query>\n{m.get('content', '')}\n</user_query>"))
        elif m.get("role") == "assistant":
            out.append(AIMessage(m.get("content", "")))
    return out


def run_turn(
    default_kb: str | None,
    user_message: str,
    history: list[dict] | None = None,
) -> Iterator[dict]:
    registry: dict[int, Hit] = {}
    kb_names = {kb.name for kb in list_kbs()}
    checkpointer = MemorySaver()  # 每轮新实例 + 新 thread，退出即弃（跨轮真相是 history）
    config = {"configurable": {"thread_id": uuid4().hex}}
    graph = _build_graph(default_kb, registry, checkpointer)
    maybe_trigger_maintenance()  # 长期记忆周期整理：每轮开头检查（写入侧亦有检查）

    try:
        regenerated = False
        yield from _pass(
            graph,
            {
                "messages": [
                    SystemMessage(build_system_prompt(default_kb)),
                    *_history_messages(history),
                    # 用户问题也走标签通道（与 tool_output 的资料通道对称）
                    HumanMessage(f"<user_query>\n{user_message}\n</user_query>"),
                ],
                "rounds": 0,
            },
            config,
        )

        while True:
            state = graph.get_state(config).values
            last = state["messages"][-1]

            # 流结束但末条仍带 tool_calls ⇒ 触达 MAX_ROUNDS 被截断
            if getattr(last, "tool_calls", None):
                yield {"type": "error",
                       "message": f"工具循环超过 {MAX_ROUNDS} 轮上限，已停止"}
                return

            content = _text_of(last)
            violations = validate_citations(content, registry.values(), kb_names)
            if violations and not regenerated and state.get("rounds", 0) < MAX_ROUNDS:
                regenerated = True
                yield {"type": "reset"}
                yield {"type": "tool", "name": "citation_check",
                       "summary": f"{len(violations)} 处引用不在检索结果中，重新生成"}
                yield from _pass(
                    graph,
                    {"messages": [HumanMessage(
                        _REGEN_PROMPT.format(violations="\n".join(violations))
                    )]},
                    config,
                )
                continue

            hits = sorted(registry.values(), key=lambda h: h.score, reverse=True)
            yield {"type": "citations",
                   "citations": [citation_of(h, i + 1) for i, h in enumerate(hits)]}
            yield {"type": "done"}
            return
    except Exception as e:  # noqa: BLE001
        yield {"type": "error", "message": str(e)}
