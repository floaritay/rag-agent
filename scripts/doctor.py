"""开发自检：环境/配置/目录/LangChain 依赖/硅基流动三接口连通性。

用法：在已安装本项目（pip install -e ".[dev]"）的 Python 环境中运行
`python scripts/doctor.py`。
退出码：全部必需项通过为 0，否则为 1。
"""

from __future__ import annotations

import httpx
from ragagent.config import (
    KNOWLEDGE_BASE_DIR,
    PROJECT_ROOT,
    STORAGE_DIR,
    get_settings,
    load_app_config,
)

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results: list[tuple[str, str, str]] = []  # (名称, 状态, 详情)


def record(name: str, status: str, detail: str = "") -> None:
    results.append((name, status, detail))


def check(name: str, fn):
    try:
        detail = fn()
        record(name, PASS, detail or "")
    except Exception as e:  # noqa: BLE001 —— 自检脚本吞掉一切异常转为 FAIL
        record(name, FAIL, str(e))


def check_python() -> str:
    import sys

    if sys.version_info < (3, 11):
        raise RuntimeError(f"需要 Python >= 3.11，当前 {sys.version.split()[0]}")
    return sys.version.split()[0]


def check_env_file() -> str:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        raise RuntimeError(".env 不存在，请从 .env.example 复制")
    return "存在"


def check_dirs() -> str:
    for d in (KNOWLEDGE_BASE_DIR, STORAGE_DIR):
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    return "knowledge_base/ 与 storage/ 可写"


def check_config() -> str:
    cfg = load_app_config()
    names = [kb.name for kb in cfg.knowledge_bases]
    return f"已注册知识库: {names or '无'}; chunk={cfg.chunking.chunk_size}/{cfg.chunking.overlap}"


def check_langchain() -> str:
    from importlib.metadata import version

    # 真实 import 一遍，确保不是只有包名存在
    import langchain  # noqa: F401
    import langchain_chroma  # noqa: F401
    import langchain_classic  # noqa: F401
    import langchain_openai  # noqa: F401
    import langgraph  # noqa: F401

    parts = [
        f"{name} {version(dist)}"
        for name, dist in [
            ("langchain", "langchain"),
            ("chroma", "langchain-chroma"),
            ("openai", "langchain-openai"),
            ("langgraph", "langgraph"),
            ("classic", "langchain-classic"),
        ]
    ]
    return ", ".join(parts)


def http_client(base_url: str | None = None, api_key: str | None = None) -> httpx.Client:
    """三类服务各有生效地址/密钥（按服务覆盖 || 共享），缺省用共享值。"""
    s = get_settings()
    return httpx.Client(
        base_url=base_url or s.siliconflow_base_url,
        headers={"Authorization": f"Bearer {api_key or s.siliconflow_api_key}"},
        timeout=30,
    )


def check_chat(client: httpx.Client, model: str) -> str:
    # 流式探测：非流式接口抖动大（max_tokens=1 也可能排队 >30s 触发 ReadTimeout），
    # 流式首字节稳定在 1s 内，读到首个 data 帧即证明模型可用。
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "stream": True,
    }
    with client.stream("POST", "/chat/completions", json=payload) as r:
        if r.status_code != 200:
            body = r.read().decode("utf-8", errors="replace")[:200]
            raise RuntimeError(f"HTTP {r.status_code}: {body}")
        for line in r.iter_lines():
            if line.startswith("data:"):
                break
        else:
            raise RuntimeError("流式响应未收到 data 帧")
    return f"{model} 可用"


def check_embed(client: httpx.Client, model: str) -> str:
    r = client.post("/embeddings", json={"model": model, "input": ["连通性测试"]})
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    dim = len(r.json()["data"][0]["embedding"])
    return f"{model} 可用，{dim} 维"


def check_rerank(client: httpx.Client, model: str) -> str:
    r = client.post(
        "/rerank",
        json={"model": model, "query": "连通性测试", "documents": ["知识库检索", "天气查询"]},
    )
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    return f"{model} 可用"


def main() -> int:
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    s = get_settings()
    check("[1] Python >= 3.11", check_python)
    check("[2] .env 存在", check_env_file)
    check("[3] API Key 已配置", lambda: (_ for _ in ()).throw(RuntimeError("请在 .env 填入 SILICONFLOW_API_KEY")) if not s.key_configured else "已配置")
    check("[4] config.yaml 可加载", check_config)
    check("[5] 目录可写", check_dirs)
    check("[6] LangChain 依赖", check_langchain)

    if s.key_configured:
        # 三类服务各自走生效地址/密钥（按服务覆盖 || 共享）
        with http_client(s.chat_base, s.chat_key) as c_chat, \
                http_client(s.embed_base, s.embed_key) as c_embed, \
                http_client(s.rerank_base, s.rerank_key) as c_rerank:
            check("[7] chat 接口", lambda: check_chat(c_chat, s.chat_model))
            check("[8] embeddings 接口", lambda: check_embed(c_embed, s.embed_model))
            check("[9] rerank 接口", lambda: check_rerank(c_rerank, s.rerank_model))
    else:
        for name in ("[7] chat 接口", "[8] embeddings 接口", "[9] rerank 接口"):
            record(name, SKIP, "未配置 API Key")

    n_pass = sum(1 for _, st, _ in results if st == PASS)
    n_fail = sum(1 for _, st, _ in results if st == FAIL)
    n_skip = sum(1 for _, st, _ in results if st == SKIP)

    print()
    for name, st, detail in results:
        mark = {"PASS": "[✓]", "FAIL": "[✗]", "SKIP": "[-]"}[st]
        line = f"{mark} {st:<4} {name}"
        if detail:
            line += f" —— {detail}"
        print(line)
    print(f"\n结果: {n_pass} 通过, {n_fail} 失败, {n_skip} 跳过")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
