# RAG Agent · 个人本地知识库智能体

以 RAG 为核心的个人 Agent：把散落在 md / txt / docx / pptx / xlsx / pdf 里的知识资产
建成可问答的本地知识库。除模型调用走硅基流动云 API 外，数据处理、索引、检索、
服务全部在本机完成。

## 功能

- **多知识库**：库之间索引完全隔离，界面上随手切换
- **六格式入库**：md / txt / docx / pptx / xlsx / pdf；表格统一转 Markdown 整块入库
  （xlsx 长表按行分块、每块重复表头）；doc / ppt 需手动另存为 docx / pptx 后入库；
  **图片抽图入库**（pdf/docx/pptx → VLM 看图说明 + DeepSeek-OCR 逐字文字合并为可检索 caption，报告注明张数），
  扫描件 PDF 走 MinerU 解析，回答命中图片时自动附给多模态对话模型；单文档图片上限 `IMAGE_MAX_PER_DOC`（默认 20，≤0 不限），单图 >15MB 自动跳过
- **增量入库**：sha256 未变的文件自动跳过；失败文件保留可重试
- **混合检索**（LangChain）：向量（langchain-chroma，bge-m3）+ BM25（jieba，
  langchain BM25Retriever）→ EnsembleRetriever RRF 融合 → bge-reranker-v2-m3 精排
  （langchain 压缩器封装；重排失败自动降级，config 可关）
- **Agent 问答**（LangGraph）：function-calling 工具循环（≤8 轮），11 个工具
  （4 个 RAG 检索 + 2 个长期记忆 + 5 个子代理管理：spawn / wait / send / cancel / list）；
  引用白名单校验——答案里的每条 `[来源: …]` 必须来自本轮检索结果，违规模型自动重生成；
  检索不到时明说，通用知识补充分段标注 ⚠️
- **多会话 + 持久化**：聊天页侧栏支持多个会话（新建 / 切换 / 重命名 / 删除），
  历史存服务端 SQLite（`meta.db`），刷新不丢；历史随请求喂给模型，对话有上下文记忆
- **长期记忆**：跨会话的用户偏好/事实由模型自主读写（recall / remember 两个工具，
  不自动注入提示词）；remember 带 id 即更新；激活条数超过 24 时后台自动整理
  （合并相近、淘汰过时、归纳压缩到约 12 条），整理失败静默重试
- **子代理**：深挖类任务可委派后台子代理（research 调研员 / general 通才），
  主线程不阻塞；spawn / list / send 追问 / cancel 管理，运行中上限 2 个，
  单代理 ≤6 轮，结果作为资料回传主线程（引用需自行核验）
- **纯 Web**：按产品设计稿实现的深色三页 UI——落地页 / 聊天页（流式思考过程·结束后
  收起 / 流式回答 / 工具调用卡 / 引用来源卡 / 会话搜索与日期分组）/ 知识库页（统计卡 /
  拖拽上传 / 文件表 / 切分预览 / 逐文档重索引 / 后台入库实时进度），单进程单端口；
  React 18 + Vite + Tailwind v4

## 快速开始

前置：Python 3.11+（conda / venv / uv 任选，已在 Windows 验证）、一个
[硅基流动](https://siliconflow.cn) API Key；改前端时另需 Node 18+。

```bash
# 先激活你的 Python 环境（conda / venv / uv 均可，依赖由 pip 安装）
conda activate <环境名>                  # 示例；venv 则 source .venv/bin/activate
pip install -e ".[dev]"                  # 安装本项目及全部依赖（带 uv 锁定也可用 uv sync）
cp .env.example .env                     # Windows：copy .env.example .env
                                         # 填入 SILICONFLOW_API_KEY（也可稍后在网页 ⚙ 设置里改）
python scripts/doctor.py                 # 自检：9 项全绿即就绪
python scripts/seed_demo.py              # 可选：生成样例文档到 knowledge_base/demo
python -m uvicorn ragagent.server.app:app --port 8000
```

浏览器打开 <http://127.0.0.1:8000>（**默认进入对话页**；hash 路由：`#/chat` 对话 · `#/kb` 知识库 · `#/` 产品首页）：

- **首页**：产品落地页，CTA 跳转对话/知识库
- **对话页**：选库 → 提问。思考模式实时展示模型推理过程（回答结束后默认收起，
  点击可展开，工具调用以卡片内嵌）；回答带引用来源卡（文件 + 位置 + 原文片段，点开收起）；
  侧栏多会话（搜索 / 今天·昨天·更早分组 / 改名 / 删除）
- **知识库页**：建库 → 拖拽或点击上传（**大文件后台入库 + 实时进度**，上传流式写盘、
  无大小文案限制）→ 统计卡（文档/切片/索引状态/占用空间）与文件表（类型/大小/状态/
  时间/👁 切分效果预览/逐文档重索引；删除连同磁盘原始文件）→ 入库报告

## 配置

`.env`（敏感项）：

| 变量 | 说明 |
|------|------|
| `SILICONFLOW_BASE_URL` / `SILICONFLOW_API_KEY` | 硅基流动接口与密钥 |
| `CHAT_MODEL` | 对话模型，默认 `deepseek-ai/DeepSeek-V4-Flash` |
| `EMBED_MODEL` | 嵌入模型，默认 `BAAI/bge-m3`（1024 维） |
| `RERANK_MODEL` | 重排模型，默认 `BAAI/bge-reranker-v2-m3` |
| `APP_HOST` / `APP_PORT` | 服务监听地址端口 |
| `CHAT_BASE_URL` / `CHAT_API_KEY` 等 6 个可选键 | **按服务覆盖**（`CHAT_*`/`EMBED_*`/`RERANK_*` 各一对）：留空回退共享的 `SILICONFLOW_*`，可为三类模型分别配置不同供应商/密钥；也可在网页 ⚙ 设置中配置（写回 `.env`）。地址需 OpenAI 兼容，重排需兼容 `/rerank` 协议 |

`config.yaml`：知识库注册（管理页会自动维护）、分块参数（chunk 500 / overlap 80）、
检索参数（vector_k 8 / bm25_k 8 / rrf_k 60 / top_n 6）、`rerank_enabled` 开关。

## 工程结构

```
├─ config.yaml / .env           # 配置（知识库注册 / 模型密钥）
├─ knowledge_base/<库名>/        # 你的文档（不入库 git）
├─ storage/                      # 运行时产物：chroma / bm25 / meta.db
├─ src/ragagent/
│  ├─ config.py  storage.py     # 配置与 SQLite 元数据（kb/document/chunk）
│  ├─ ingest/                    # 解析 → 分块 → langchain-chroma 嵌入入 / BM25 / SQLite
│  ├─ retrieve/                  # LangChain Retriever + EnsembleRetriever 融合 → 重排
│  ├─ agent/                     # 提示词 / 4 工具 / 引用白名单 / LangGraph 工具循环
│  ├─ llm.py  ingest/embeddings.py  # ChatOpenAI / OpenAIEmbeddings 工厂（硅基流动）
│  └─ server/                    # FastAPI 路由 + React 前端（web/）
└─ scripts/                      # doctor 自检 / seed_demo 样例
```

## 已知限制

- 图片文字化由 `IMAGE_DESCRIBE` 全局开关控制（默认开；OCR 密钥未配时 caption 退化占位）；
  扫描件 PDF 需在 .env 配 `MinerU=` 密钥才能提取文字；xlsx / md / txt 内嵌图不抽
- 回答附原图依赖对话模型的多模态能力——纯文本模型自动降级为仅文字（⚙ 设置可一键探测）
- doc / ppt 不做自动转换，入库时报错引导手动另存
- 单用户单机，无鉴权——不要把端口暴露到公网
