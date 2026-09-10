/** 画布生成条：多选 Agent Skill */
import { useEffect, useRef, useState, type MouseEvent } from 'react'
import { ChevronDown, Wand2 } from 'lucide-react'
import { AgentSkillPicker } from '../../../../components/drama/AgentSkillPicker'
import { skillTriggerLabel } from '../../../../lib/agentSkillSelection'
import type { AgentSkill } from '../../../../api/agentSkills'
import './dramaImageGenOptions.css'

type DramaSkillOptionsBarProps = {
  skills: AgentSkill[]
  selectedIds: number[]
  onToggle: (skillId: number) => void
  onSelectAll: () => void
  onSelectNone: () => void
  onUpload: (file: File) => void
  uploading?: boolean
  uploadError?: string
  disabled?: boolean
}

/** 渲染 Skill 下拉多选 */
export function DramaSkillOptionsBar({
  skills,
  selectedIds,
  onToggle,
  onSelectAll,
  onSelectNone,
  onUpload,
  uploading = false,
  uploadError = '',
  disabled = false,
}: DramaSkillOptionsBarProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    function onDoc(event: Event) {
      const target = event.target as Node | null
      if (rootRef.current && target && !rootRef.current.contains(target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const stop = (event: MouseEvent) => {
    event.stopPropagation()
  }

  const label = skillTriggerLabel(skills, selectedIds)
  const active = open || selectedIds.length > 0

  return (
    <div ref={rootRef} className="fc-gen-opts fc-gen-skill-opts" onMouseDown={stop} onPointerDown={stop}>
      <div className="fc-gen-opts-triggers">
        <button
          type="button"
          className={`fc-gen-opt-btn${active ? ' active' : ''}`}
          disabled={disabled}
          onClick={() => setOpen((curr) => !curr)}
        >
          <Wand2 size={14} strokeWidth={1.8} />
          <span className="fc-gen-opt-label">{label}</span>
          <ChevronDown size={12} />
        </button>
      </div>
      {open ? (
        <div className="fc-gen-opt-panel" role="dialog" aria-label="选择 Skill">
          <div className="fc-gen-opt-panel-title">Skill</div>
          <AgentSkillPicker
            compact
            skills={skills}
            selectedIds={selectedIds}
            onToggle={onToggle}
            onSelectAll={onSelectAll}
            onSelectNone={onSelectNone}
            onUpload={onUpload}
            uploading={uploading}
            uploadError={uploadError}
          />
        </div>
      ) : null}
    </div>
  )
}
