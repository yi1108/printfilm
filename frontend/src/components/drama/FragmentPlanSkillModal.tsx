/** AI 重新分镜确认：可选本次注入的 Agent Skill */
import { useEffect } from 'react'
import { AlertTriangle } from 'lucide-react'
import { AgentSkillPicker } from './AgentSkillPicker'
import { useAgentSkillSelection } from '../../hooks/useAgentSkillSelection'

type FragmentPlanSkillModalProps = {
  open: boolean
  title?: string
  message: string
  confirmText?: string
  onCancel: () => void
  onConfirm: (skillIds: number[]) => void
}

/** 覆盖分镜前让用户勾选 Skill */
export function FragmentPlanSkillModal({
  open,
  title = 'AI 重新分镜',
  message,
  confirmText = '开始分镜',
  onCancel,
  onConfirm,
}: FragmentPlanSkillModalProps) {
  const { skills, selectedIds, toggleSkill, selectAll, selectNone, uploadSkill, uploading, uploadError } =
    useAgentSkillSelection()

  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = prev
      window.removeEventListener('keydown', onKey)
    }
  }, [open, onCancel])

  if (!open) return null

  return (
    <div className="pf-dialog-root" role="presentation">
      <div className="pf-dialog-veil" aria-hidden onMouseDown={onCancel} />
      <form
        className="pf-dialog pf-dialog--danger pf-dialog--skills"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="fragment-plan-skill-title"
        onSubmit={(event) => {
          event.preventDefault()
          onConfirm(selectedIds)
        }}
      >
        <div className="pf-dialog-glow" aria-hidden />
        <div className="pf-dialog-header">
          <div className="pf-dialog-mark" aria-hidden>
            <AlertTriangle size={22} strokeWidth={1.75} />
          </div>
          <div className="pf-dialog-body">
            <h2 id="fragment-plan-skill-title" className="pf-dialog-title">
              {title}
            </h2>
            <p className="pf-dialog-message">{message}</p>
          </div>
        </div>
        <div className="pf-dialog-skill-block">
          <div className="pf-dialog-skill-label">本次使用的 Skill</div>
          <AgentSkillPicker
            skills={skills}
            selectedIds={selectedIds}
            onToggle={toggleSkill}
            onSelectAll={selectAll}
            onSelectNone={selectNone}
            onUpload={(file) => void uploadSkill(file)}
            uploading={uploading}
            uploadError={uploadError}
            emptyText="还没有 Skill，可上传 .md"
          />
        </div>
        <div className="pf-dialog-actions">
          <button type="button" className="pf-dialog-btn pf-dialog-btn-ghost" onClick={onCancel}>
            取消
          </button>
          <button type="submit" className="pf-dialog-btn pf-dialog-btn-danger">
            {confirmText}
          </button>
        </div>
      </form>
    </div>
  )
}
