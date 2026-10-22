import React, { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown } from 'lucide-react'

/**
 * 深色主题自定义下拉（替代原生 <select> 的系统白色弹层）：
 * 触发按钮 + 悬浮菜单，点击外部关闭，选中项靛蓝高亮 + ✓。
 */
export default function Dropdown({ value, options, onChange, placeholder = '（未选择）', minWidth = 180 }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const current = options.find((o) => o.value === value)

  return (
    <div className="relative" ref={ref}>
      <button type="button" onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox" aria-expanded={open}
        className="flex items-center gap-2 rounded-lg border border-border bg-background text-foreground text-sm pl-3 pr-2.5 py-1.5 hover:bg-muted focus:outline-none focus:ring-2 focus:ring-ring transition-colors max-w-[220px]">
        <span className="truncate">{current?.label ?? placeholder}</span>
        <ChevronDown className={`w-4 h-4 text-muted-foreground transition-transform flex-shrink-0 ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-1 rounded-lg border border-border bg-popover py-1 overflow-y-auto"
          style={{ minWidth, maxHeight: 320, boxShadow: 'var(--rag-shadow-2)' }}
          role="listbox">
          {options.map((o) => (
            <button key={String(o.value)} type="button" role="option"
              aria-selected={o.value === value}
              onClick={() => { onChange(o.value); setOpen(false) }}
              className={`w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-muted focus:outline-none focus-visible:bg-muted ${
                o.value === value ? 'text-primary font-medium' : 'text-foreground'}`}>
              <span className="flex-1 truncate">{o.label}</span>
              {o.value === value && <Check className="w-4 h-4 flex-shrink-0" />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
