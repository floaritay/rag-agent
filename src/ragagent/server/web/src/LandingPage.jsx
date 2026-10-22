import React from 'react'
import {
  Bot, Search, Database, Sparkles, Workflow, FileUp, Layers, CheckCircle,
  ChevronRight, Building2, MessageSquare, FileCheck,
} from 'lucide-react'

const CAPABILITIES = [
  { icon: Search, title: '智能检索', desc: '基于向量语义与关键词混合检索，精准定位答案来源，告别关键词堆砌。' },
  { icon: Database, title: '知识增强', desc: '自动切分、索引与向量化私有文档，持续更新知识库，保证回答时效性。' },
  { icon: Sparkles, title: '生成推理', desc: '结合检索上下文与大模型推理能力，输出结构化、可落地的专业回答。' },
  { icon: Workflow, title: 'Agent 编排', desc: '可视化编排多步骤工作流，串联检索、工具调用与审批节点。' },
]

const STEPS = [
  { icon: FileUp, title: '上传文档', desc: '支持 PDF、Word、Markdown 等多格式批量导入。' },
  { icon: Layers, title: '切分索引', desc: '智能分块与元数据提取，构建高效向量索引。' },
  { icon: Search, title: '语义检索', desc: '混合检索召回最相关片段，并给出相似度排序。' },
  { icon: Sparkles, title: '大模型生成', desc: '基于检索上下文进行推理，生成专业且可落地的回答。' },
  { icon: CheckCircle, title: '结果溯源', desc: '每个回答都附带引用来源，支持一键定位原文。' },
]

const USECASES = [
  {
    icon: Building2, title: '企业知识问答',
    items: [
      '统一接入制度、手册与项目文档，秒级响应员工提问。',
      '回答附带原文引用，降低信息误传风险。',
      '支持权限隔离，不同角色看到不同范围知识。',
    ],
  },
  {
    icon: MessageSquare, title: '智能客服',
    items: [
      '基于产品知识库自动生成精准回复，减少人工排队。',
      '多轮对话保持上下文，自动调用工单与订单工具。',
      '未知问题自动升级，持续学习新 FAQ。',
    ],
  },
  {
    icon: FileCheck, title: '文档审计',
    items: [
      '快速扫描合同、报告与合规文件，提取关键条款。',
      '交叉比对多份文档，标记潜在风险与不一致。',
      '生成审计摘要与可追溯引用，提升合规效率。',
    ],
  },
]

// 原型配图缺失（破图）→ 内联 SVG 迷你产品示意
function HeroMock() {
  return (
    <svg viewBox="0 0 560 360" className="w-full h-auto" role="img" aria-label="RAG-Agent 示意图">
      <rect width="560" height="360" fill="#14141a" />
      <rect x="0" y="0" width="560" height="36" fill="#1e1e28" />
      <circle cx="18" cy="18" r="5" fill="#2a2a36" />
      <circle cx="36" cy="18" r="5" fill="#2a2a36" />
      <circle cx="54" cy="18" r="5" fill="#2a2a36" />
      <rect x="0" y="36" width="150" height="324" fill="#1a1a22" />
      <rect x="14" y="52" width="122" height="26" rx="6" fill="#4f46e5" />
      <rect x="14" y="90" width="122" height="18" rx="5" fill="#2a2a36" />
      <rect x="14" y="118" width="122" height="18" rx="5" fill="#232330" />
      <rect x="14" y="146" width="122" height="18" rx="5" fill="#232330" />
      <rect x="168" y="56" width="280" height="58" rx="12" fill="#4f46e5" />
      <rect x="184" y="72" width="248" height="8" rx="4" fill="#a5b4fc" opacity=".8" />
      <rect x="184" y="88" width="180" height="8" rx="4" fill="#a5b4fc" opacity=".55" />
      <rect x="196" y="132" width="344" height="118" rx="12" fill="#181820" stroke="#2a2a36" />
      <rect x="212" y="146" width="140" height="14" rx="4" fill="#2a2a36" />
      <rect x="212" y="170" width="312" height="8" rx="4" fill="#33333f" />
      <rect x="212" y="186" width="290" height="8" rx="4" fill="#33333f" />
      <rect x="212" y="208" width="200" height="8" rx="4" fill="#33333f" />
      <rect x="212" y="224" width="160" height="8" rx="4" fill="#4f46e5" opacity=".7" />
      <rect x="196" y="262" width="344" height="44" rx="10" fill="#14141a" stroke="#2a2a36" />
      <rect x="212" y="278" width="230" height="8" rx="4" fill="#2f2f3b" />
      <circle cx="516" cy="284" r="14" fill="#4f46e5" />
      <path d="M510 284h12m-5-5 5 5-5 5" stroke="#fff" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="196" y="318" width="344" height="28" rx="10" fill="#181820" stroke="#2a2a36" />
      <rect x="208" y="326" width="86" height="12" rx="4" fill="#4f46e5" opacity=".55" />
      <rect x="302" y="326" width="60" height="12" rx="4" fill="#2a2a36" />
      <rect x="370" y="326" width="104" height="12" rx="4" fill="#2a2a36" />
    </svg>
  )
}

export default function LandingPage() {
  return (
    <main className="min-h-screen font-sans antialiased" style={{ fontFamily: 'var(--rag-font-sans)' }}>
      {/* Hero */}
      <section id="section-hero" className="relative bg-background">
        <div className="pt-24 pb-16 lg:pt-32 lg:pb-24">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-16 items-center">
              <div className="space-y-8">
                <div className="space-y-4">
                  <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight leading-tight text-foreground">
                    RAG 智能体平台
                  </h1>
                  <p className="text-lg sm:text-xl text-muted-foreground leading-relaxed max-w-xl">
                    连接私有文档与大模型，构建可溯源、可编排、可落地的企业知识助手。
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-4">
                  <a href="#/chat" className="inline-flex items-center justify-center rounded-lg bg-primary text-primary-foreground px-6 py-3 text-base font-medium hover:bg-primary/90 active:scale-[0.98] transition-[transform,background-color]">
                    免费试用
                  </a>
                  <a href="#section-workflow" className="inline-flex items-center justify-center rounded-lg bg-secondary text-secondary-foreground px-6 py-3 text-base font-medium hover:bg-secondary/80 active:scale-[0.98] transition-[transform,background-color]">
                    查看文档
                  </a>
                </div>
              </div>
              <div className="relative">
                <div className="rounded-2xl overflow-hidden bg-card border border-border" style={{ boxShadow: 'var(--rag-shadow-1)' }}>
                  <HeroMock />
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 核心能力 */}
      <section id="section-capabilities" className="py-16 lg:py-24 bg-muted">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="max-w-2xl mx-auto text-center mb-12 lg:mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold leading-tight text-foreground mb-4">核心能力</h2>
            <p className="text-lg text-muted-foreground leading-relaxed">覆盖检索、增强、生成与编排的全链路 RAG 能力，让大模型真正读懂企业知识。</p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 lg:gap-8">
            {CAPABILITIES.map(({ icon: Icon, title, desc }) => (
              <article key={title} className="rounded-lg bg-card border border-border p-6 lg:p-8 hover:border-primary/30 transition-colors" style={{ boxShadow: 'var(--rag-shadow-1)' }}>
                <div className="flex items-start gap-4">
                  <Icon className="w-6 h-6 text-primary mt-1 flex-shrink-0" />
                  <div>
                    <h3 className="text-xl font-semibold text-foreground mb-2 leading-snug">{title}</h3>
                    <p className="text-muted-foreground leading-relaxed">{desc}</p>
                  </div>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* 工作流 */}
      <section id="section-workflow" className="py-16 lg:py-24 bg-background">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="max-w-2xl mx-auto text-center mb-12 lg:mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold leading-tight text-foreground mb-4">RAG-Agent 工作流</h2>
            <p className="text-lg text-muted-foreground leading-relaxed">五步完成从文档到可信答案的闭环，每一步都清晰可见、可干预、可审计。</p>
          </div>
          <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-0 md:gap-2">
            {STEPS.map(({ icon: Icon, title, desc }, i) => (
              <React.Fragment key={title}>
                <div className="relative flex gap-4 md:flex-1 md:flex-col md:items-center md:text-center py-4 md:px-2">
                  {i < STEPS.length - 1 && (
                    <div className="absolute left-5 top-12 bottom-0 w-px bg-border md:hidden" />
                  )}
                  <div className="relative z-10 flex-shrink-0 w-10 h-10 rounded-full bg-muted border border-border flex items-center justify-center text-primary">
                    <Icon className="w-5 h-5" />
                  </div>
                  <div className="flex-1">
                    <span className="text-xs font-medium text-primary">步骤 {i + 1}</span>
                    <h3 className="text-base font-semibold text-foreground mt-1">{title}</h3>
                    <p className="text-sm text-muted-foreground mt-1 leading-relaxed">{desc}</p>
                  </div>
                </div>
                {i < STEPS.length - 1 && (
                  <div className="hidden md:flex items-center pt-5 text-muted-foreground">
                    <ChevronRight className="w-5 h-5" />
                  </div>
                )}
              </React.Fragment>
            ))}
          </div>
        </div>
      </section>

      {/* 典型场景 */}
      <section id="section-usecases" className="py-16 lg:py-24 bg-muted">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="max-w-2xl mx-auto text-center mb-12 lg:mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold leading-tight text-foreground mb-4">典型场景</h2>
            <p className="text-lg text-muted-foreground leading-relaxed">面向个人与小团队的本地知识库场景，数据处理全部在本机完成。</p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 lg:gap-8">
            {USECASES.map(({ icon: Icon, title, items }) => (
              <article key={title} className="rounded-lg bg-card border border-border p-6 lg:p-8" style={{ boxShadow: 'var(--rag-shadow-1)' }}>
                <div className="flex items-center gap-3 mb-4">
                  <Icon className="w-6 h-6 text-primary" />
                  <h3 className="text-xl font-semibold text-foreground leading-snug">{title}</h3>
                </div>
                <ul className="space-y-3 text-muted-foreground leading-relaxed">
                  {items.map((t) => (
                    <li key={t} className="flex gap-2"><span className="text-primary mt-1.5">•</span><span>{t}</span></li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* CTA + 页脚 */}
      <section id="section-cta" className="bg-primary text-primary-foreground py-16 lg:py-24">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <div className="space-y-6">
            <h2 className="text-3xl sm:text-4xl font-bold leading-tight">立即部署你的 RAG-Agent</h2>
            <p className="text-lg text-primary-foreground/80 leading-relaxed max-w-2xl mx-auto">无论是内部知识库、客服坐席还是合规审计，RAG-Agent 都能帮你快速落地安全可信的大模型应用。</p>
            <div className="flex flex-wrap justify-center gap-4 pt-2">
              <a href="#/chat" className="inline-flex items-center justify-center rounded-lg bg-primary-foreground text-primary px-6 py-3 text-base font-medium hover:bg-primary-foreground/90 active:scale-[0.98] transition-[transform,background-color]">
                免费试用
              </a>
              <a href="#/kb" className="inline-flex items-center justify-center rounded-lg border border-primary-foreground/30 text-primary-foreground px-6 py-3 text-base font-medium hover:bg-primary-foreground/10 active:scale-[0.98] transition-[transform,background-color]">
                管理知识库
              </a>
            </div>
          </div>
        </div>
        <footer className="mt-16 border-t border-primary-foreground/20 pt-8">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col md:flex-row justify-between items-center gap-4 text-sm text-primary-foreground/70">
            <p>© 2026 RAG-Agent. 保留所有权利。</p>
            <div className="flex items-center gap-6">
              <a href="#/" className="hover:text-primary-foreground transition-colors rounded">隐私政策</a>
              <a href="#/" className="hover:text-primary-foreground transition-colors rounded">服务条款</a>
              <a href="#/" className="hover:text-primary-foreground transition-colors rounded">GitHub</a>
            </div>
          </div>
        </footer>
      </section>
    </main>
  )
}
