"""诊断：对一个超轮失败问题逐轮打印 模型输入消息/输出，定位死循环原因。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

import ragagent.agent.loop as loop_mod
from ragagent.llm import make_chat_model as real_factory

state = {"n": 0}


def debug_factory():
    real = real_factory()  # 已 bind_tools

    class Wrapper:
        def stream(self, messages):
            state["n"] += 1
            n = state["n"]
            print(f"\n===== round {n}: 输入 {len(messages)} 条 =====")
            for m in messages:
                kind = type(m).__name__
                extra = ""
                if getattr(m, "tool_calls", None):
                    extra = f" tool_calls={[ (t.get('name'), t.get('id')) for t in m.tool_calls ]}"
                if kind == "ToolMessage":
                    extra = f" id={m.tool_call_id} content={m.content[:120]!r}"
                elif kind in ("SystemMessage", "HumanMessage", "AIMessage"):
                    c = m.content if isinstance(m.content, str) else str(m.content)
                    extra = f" content={c[:100]!r}"
                print(f"  - {kind}{extra}")
            acc = None
            for chunk in real.stream(messages):
                acc = chunk if acc is None else acc + chunk
                yield chunk
            print(f"  -> 回复: content={getattr(acc, 'content', '')!r}")
            print(f"  -> tool_calls={getattr(acc, 'tool_calls', None)}")

    return Wrapper()


loop_mod.make_chat_model = debug_factory

question = sys.argv[1] if len(sys.argv) > 1 else "预算表中 row45 的 Q3 值是多少？"
kb = sys.argv[2] if len(sys.argv) > 2 else "demo"
print(f"问题: {question}  库: {kb}")
for ev in loop_mod.run_turn(kb, question):
    t = ev["type"]
    if t == "token":
        print(f"[token] {ev['text']}", end="")
    elif t == "tool":
        print(f"\n[tool] {ev['name']}: {ev['summary']}")
    else:
        print(f"\n[{t}] {str(ev)[:200]}")
