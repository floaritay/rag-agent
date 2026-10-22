// 极简 Markdown 渲染：先整体 HTML 转义，再做有限变换，避免注入
// 支持：标题 #、无序/有序列表、**加粗**、`行内代码`、[来源:…] 标签、
//       GFM 表格（含 \| 转义）、``` 代码块、> 引用块

const CELL_PIPE = '@@PIPE@@'  // 单元格内 \|（转义竖线）占位，split('|') 前保护

export function mdToHtml(src) {
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const inline = (s) => s
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\[来源:([^\]]+)\]/g, '<span class="cite-tag">[来源:$1]</span>')
  const lines = esc(src || '').split(/\r?\n/)

  const stripPipes = (l) => l.trim().replace(/^\|/, '').replace(/\|$/, '')
  const cells = (l) => stripPipes(l)
    .replace(/\\\|/g, CELL_PIPE)               // 保护转义竖线
    .split('|')
    .map((c) => inline(c.trim().split(CELL_PIPE).join('|')))
  const isSepRow = (l) => {
    if (!/^\s*\|/.test(l)) return false
    const cs = stripPipes(l).split('|').map((c) => c.trim())
    return cs.length > 0 && cs.every((c) => /^:?-+:?$/.test(c))
  }

  const out = []
  let inList = false
  const closeList = () => { if (inList) { out.push('</ul>'); inList = false } }
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    // ``` 代码块：围栏内原样保留（已整体转义），不做行内变换
    if (/^\s*```/.test(line)) {
      closeList()
      const buf = []
      i++
      while (i < lines.length && !/^\s*```/.test(lines[i])) { buf.push(lines[i]); i++ }
      i++  // 吃掉收尾围栏（或 EOF）
      out.push(`<pre class="md-pre"><code>${buf.join('\n')}</code></pre>`)
      continue
    }

    // GFM 表格：表头行 + 紧随的分隔行（|---|:--:|）
    if (/^\s*\|/.test(line) && i + 1 < lines.length && isSepRow(lines[i + 1])) {
      closeList()
      const header = cells(line)
      i += 2
      const rows = []
      while (i < lines.length && /^\s*\|/.test(lines[i])) { rows.push(cells(lines[i])); i++ }
      out.push(
        '<div class="md-table-wrap"><table class="md-table"><thead><tr>'
        + header.map((h) => `<th>${h}</th>`).join('')
        + '</tr></thead><tbody>'
        + rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join('')}</tr>`).join('')
        + '</tbody></table></div>',
      )
      continue
    }

    // > 引用块（连续行合并为一块）
    // 注意：esc 已把行首 > 转成 &gt;，按 &gt; 检测（原文的 &gt; 会被转成 &amp;gt;，不冲突）
    if (/^\s*&gt;\s?/.test(line)) {
      closeList()
      const buf = []
      while (i < lines.length && /^\s*&gt;\s?/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*&gt;\s?/, ''))
        i++
      }
      out.push(`<blockquote class="md-quote">${buf.map((l) => `<p>${inline(l)}</p>`).join('')}</blockquote>`)
      continue
    }

    const h = line.match(/^(#{1,4})\s+(.*)/)
    const li = line.match(/^\s*[-*]\s+(.*)/)
    const ol = line.match(/^\s*\d+[.、）]\s+(.*)/)
    if (h) { closeList(); out.push(`<h${h[1].length + 2}>${inline(h[2])}</h${h[1].length + 2}>`) }
    else if (li || ol) {
      if (!inList) { out.push('<ul>'); inList = true }
      out.push(`<li>${inline((li || ol)[1])}</li>`)
    }
    else if (!line.trim()) { closeList() }
    else { closeList(); out.push(`<p>${inline(line)}</p>`) }
    i++
  }
  closeList()
  return out.join('')
}
