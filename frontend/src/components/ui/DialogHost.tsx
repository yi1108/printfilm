import { useEffect, useId, useRef, useState, useSyncExternalStore, type FormEvent } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  CircleHelp,
  PencilLine,
  Sparkles,
  type LucideIcon,
} from 'lucide-react'
import {
  closeDialog,
  getDialogRequest,
  subscribeDialog,
  type DialogRequest,
  type DialogTone,
} from '../../lib/dialog'
import { useI18n } from '../../i18n'

// 按弹窗类型与语气返回图标
function dialogIcon(kind: DialogRequest['kind'], tone: DialogTone | undefined): LucideIcon {
  if (tone === 'danger') return AlertTriangle
  if (tone === 'success') return CheckCircle2
  if (kind === 'prompt') return PencilLine
  if (kind === 'confirm') return Sparkles
  return CircleHelp
}

function toneClass(tone: DialogTone | undefined) {
  if (tone === 'danger') return 'pf-dialog--danger'
  if (tone === 'success') return 'pf-dialog--success'
  return 'pf-dialog--default'
}

function dismissRequest(active: DialogRequest) {
  if (active.kind === 'confirm') active.resolve(false)
  else if (active.kind === 'prompt') active.resolve(null)
  else active.resolve()
  closeDialog()
}

function acceptRequest(active: DialogRequest, promptValue: string) {
  if (active.kind === 'confirm') active.resolve(true)
  else if (active.kind === 'prompt') active.resolve(promptValue)
  else active.resolve()
  closeDialog()
}

export default function DialogHost() {
  const { t } = useI18n()
  const req = useSyncExternalStore(subscribeDialog, getDialogRequest, getDialogRequest)
  const [promptValue, setPromptValue] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const titleId = useId()
  const descId = useId()

  useEffect(() => {
    if (!req) return
    if (req.kind === 'prompt') {
      setPromptValue(req.options.defaultValue || '')
      const t = window.setTimeout(() => inputRef.current?.focus(), 40)
      return () => window.clearTimeout(t)
    }
    setPromptValue('')
  }, [req])

  useEffect(() => {
    if (!req) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') dismissRequest(req)
    }
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = prev
      window.removeEventListener('keydown', onKey)
    }
  }, [req])

  if (!req) return null

  const active: DialogRequest = req
  const tone = active.options.tone || 'default'
  const Icon = dialogIcon(active.kind, tone)
  const title =
    active.options.title ||
    (active.kind === 'confirm'
      ? t('dialog.confirmTitle')
      : active.kind === 'prompt'
        ? t('dialog.promptTitle')
        : t('dialog.alertTitle'))
  const message =
    active.kind === 'prompt' ? active.options.message || '' : active.options.message
  const confirmText =
    active.kind === 'alert'
      ? active.options.confirmText || t('dialog.ok')
      : active.options.confirmText || t('dialog.confirm')
  const cancelText = active.kind === 'alert' ? '' : active.options.cancelText || t('dialog.cancel')

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    acceptRequest(active, promptValue)
  }

  return (
    <div className="pf-dialog-root" role="presentation">
      <div className="pf-dialog-veil" aria-hidden onMouseDown={() => dismissRequest(active)} />
      <form
        className={`pf-dialog ${toneClass(tone)}`}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={message ? descId : undefined}
        onSubmit={onSubmit}
      >
        <div className="pf-dialog-glow" aria-hidden />
        <div className="pf-dialog-header">
          <div className="pf-dialog-mark" aria-hidden>
            <Icon size={22} strokeWidth={1.75} />
          </div>
          <div className="pf-dialog-body">
            <h2 id={titleId} className="pf-dialog-title">
              {title}
            </h2>
            {message ? (
              <p id={descId} className="pf-dialog-message">
                {message}
              </p>
            ) : null}
          </div>
        </div>
        {active.kind === 'prompt' ? (
          <input
            ref={inputRef}
            className="pf-dialog-input"
            value={promptValue}
            placeholder={active.options.placeholder || ''}
            onChange={(e) => setPromptValue(e.target.value)}
          />
        ) : null}
        <div className="pf-dialog-actions">
          {cancelText ? (
            <button
              type="button"
              className="pf-dialog-btn pf-dialog-btn-ghost"
              onClick={() => dismissRequest(active)}
            >
              {cancelText}
            </button>
          ) : null}
          <button
            type="submit"
            className={[
              'pf-dialog-btn',
              tone === 'danger' ? 'pf-dialog-btn-danger' : 'pf-dialog-btn-primary',
            ].join(' ')}
            autoFocus={active.kind !== 'prompt'}
          >
            {confirmText}
          </button>
        </div>
      </form>
    </div>
  )
}
