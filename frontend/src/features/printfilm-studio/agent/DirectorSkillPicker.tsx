import type { AgentSkill } from '../../../api/agentSkills'
import { STUDIO_SKILL_TASKS, STUDIO_SKILL_LABELS, studioSkillName, studioSkillsForTask, type StudioSkillTask, type StudioSkillSelection } from './skills'

export function DirectorSkillPicker({skills,selection,task,disabled,onTask,onSelect}: {skills:AgentSkill[];selection:StudioSkillSelection;task:StudioSkillTask;disabled:boolean;onTask:(task:StudioSkillTask)=>void;onSelect:(task:StudioSkillTask,id:number|null)=>void}) {
  const selected=skills.find(skill=>skill.id===selection[task])
  return <details className="pf-director-skills">
    <summary aria-label="选择导演技能">导演技能 · {STUDIO_SKILL_LABELS[task]} · {selected ? studioSkillName(selected) : '不使用技能'}</summary>
    <div className="pf-director-phases" aria-label="导演阶段">{STUDIO_SKILL_TASKS.map(phase=><button key={phase} type="button" disabled={disabled} aria-pressed={phase===task} onClick={()=>onTask(phase)}>{STUDIO_SKILL_LABELS[phase]}</button>)}</div>
    <div className="pf-director-options" role="radiogroup" aria-label={`${STUDIO_SKILL_LABELS[task]}技能`} onKeyDown={event=>{
      if (disabled || !['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key)) return
      event.preventDefault(); event.stopPropagation()
      const choices=[...event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]')]
      const at=choices.indexOf(event.target as HTMLButtonElement)
      const next=event.key==='Home' ? 0 : event.key==='End' ? choices.length-1 : (at+(['ArrowRight','ArrowDown'].includes(event.key)?1:-1)+choices.length)%choices.length
      choices[next]?.focus(); choices[next]?.click()
    }}>
      <button type="button" role="radio" tabIndex={selection[task]===null?0:-1} aria-checked={selection[task]===null} disabled={disabled} onClick={()=>onSelect(task,null)}><b>不使用技能</b><small>保留基本创作要求</small></button>
      {studioSkillsForTask(skills,task).map(skill=><button key={skill.id} type="button" role="radio" tabIndex={selection[task]===skill.id?0:-1} aria-checked={selection[task]===skill.id} disabled={disabled} onClick={()=>onSelect(task,skill.id)}><b>{studioSkillName(skill)}</b><small>{skill.description}</small></button>)}
    </div>
    {selected && <details className="pf-director-rules"><summary>查看所选技能规则</summary><pre>{selected.body}</pre></details>}
    <p>每阶段单选，选择自动保存在此浏览器。规划完成后再选择下一步；生成仍需确认模型与费用。</p>
  </details>
}
