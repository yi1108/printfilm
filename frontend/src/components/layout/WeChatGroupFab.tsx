/** 全站右下角：加微信号入群（展示微信号，可一键复制；可拖动） */
import { useEffect, useRef, useState } from 'react'
import { Check, Copy, X } from 'lucide-react'
import { useI18n } from '../../i18n'
import { useFabDragPosition } from '../../hooks/useFabDragPosition'
import { WECHAT_ID } from '../../lib/siteContact'

/** 社区加群微信号（不加图片二维码） */
const POS_STORAGE_KEY = 'pf-wx-group-fab-pos'

/** 简易微信气泡图标 */
function WeChatIcon({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden fill="currentColor">
      <path d="M9.5 4C5.91 4 3 6.46 3 9.5c0 1.72.9 3.26 2.32 4.32L4.7 16.1l2.42-.72c.72.22 1.5.35 2.33.35.18 0 .35 0 .52-.02A4.9 4.9 0 0 1 9.5 14.5c0-2.99 2.8-5.4 6.25-5.4.1 0 .2 0 .3.01C15.4 5.9 12.7 4 9.5 4Zm-2.4 3.4a.9.9 0 1 1 0 1.8.9.9 0 0 1 0-1.8Zm4.1 0a.9.9 0 1 1 0 1.8.9.9 0 0 1 0-1.8Z" />
      <path d="M15.75 10.1c-2.9 0-5.25 1.9-5.25 4.25S12.85 18.6 15.75 18.6c.62 0 1.21-.1 1.76-.27l1.95.58-.48-1.55c1.1-.82 1.82-2 1.82-3.31 0-2.35-2.35-4.25-5.05-4.25Zm-1.7 3.1a.7.7 0 1 1 0 1.4.7.7 0 0 1 0-1.4Zm3.4 0a.7.7 0 1 1 0 1.4.7.7 0 0 1 0-1.4Z" />
    </svg>
  )
}

export default function WeChatGroupFab() {
  const { t } = useI18n()
  /*
   * open 浮层是否展开
   * copied 复制成功短暂态
   */
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const { style: fabStyle, bindDrag, consumeDragSuppressClick } = useFabDragPosition(
    POS_STORAGE_KEY,
    { right: 20, bottom: 24 },
    48,
  )

  // 点击浮层外 / Esc 关闭
  useEffect(() => {
    if (!open) return
    function onPointerDown(e: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  // 复制微信号到剪贴板
  async function copyWechatId() {
    try {
      await navigator.clipboard.writeText(WECHAT_ID)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      /* 忽略剪贴板失败，用户仍可手动选中复制 */
    }
  }

  return (
    <div className="pf-wx-fab-root is-draggable" ref={rootRef} style={fabStyle}>
      {open ? (
        <div className="pf-wx-fab-panel" role="dialog" aria-label={t('wechatGroup.title')}>
          <header className="pf-wx-fab-head">
            <div>
              <strong>{t('wechatGroup.title')}</strong>
              <p>{t('wechatGroup.lead')}</p>
            </div>
            <button
              type="button"
              className="pf-wx-fab-close"
              onClick={() => setOpen(false)}
              aria-label={t('common.close')}
            >
              <X size={16} strokeWidth={2} aria-hidden />
            </button>
          </header>
          <div className="pf-wx-fab-id">
            <span className="pf-wx-fab-id-label">{t('wechatGroup.idLabel')}</span>
            <code className="pf-wx-fab-id-value">{WECHAT_ID}</code>
            <button
              type="button"
              className="pf-wx-fab-copy"
              onClick={() => void copyWechatId()}
              aria-label={copied ? t('wechatGroup.copied') : t('wechatGroup.copy')}
            >
              {copied ? <Check size={14} strokeWidth={2.2} aria-hidden /> : <Copy size={14} strokeWidth={2} aria-hidden />}
              <span>{copied ? t('wechatGroup.copied') : t('wechatGroup.copy')}</span>
            </button>
          </div>
          <p className="pf-wx-fab-tip">{t('wechatGroup.tip')}</p>
        </div>
      ) : null}
      <button
        type="button"
        className={`pf-wx-fab-btn is-draggable${open ? ' is-open' : ''}`}
        onClick={() => {
          if (consumeDragSuppressClick()) return
          setOpen((v) => !v)
        }}
        aria-expanded={open}
        aria-label={t('wechatGroup.open')}
        title={`${t('wechatGroup.open')}（可拖动）`}
        {...bindDrag}
      >
        <WeChatIcon />
        <span className="pf-wx-fab-label">{t('wechatGroup.short')}</span>
      </button>
    </div>
  )
}
