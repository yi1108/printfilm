/** Agent Skill 勾选：本地缓存与默认值 */

import type { AgentSkill } from '../api/agentSkills'

const STORAGE_KEY = 'agentSkillIds:v1'

/** 读取上次勾选的 Skill id；无缓存返回 null */
export function loadStoredSkillIds(): number[] | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return null
    return parsed
      .map((item) => Number(item))
      .filter((id) => Number.isInteger(id) && id > 0)
  } catch {
    return null
  }
}

/** 写入勾选 Skill id */
export function saveStoredSkillIds(ids: number[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(ids))
  } catch {
    /* 隐私模式或配额满时忽略 */
  }
}

/** 默认勾选：全部启用中的 skill */
export function defaultSkillIds(skills: AgentSkill[]): number[] {
  return skills.filter((skill) => skill.is_active).map((skill) => skill.id)
}

/** 用现有列表校正缓存 id；无缓存则用默认启用项 */
export function resolveSelectedSkillIds(skills: AgentSkill[], stored: number[] | null): number[] {
  const valid = new Set(skills.map((skill) => skill.id))
  if (stored == null) return defaultSkillIds(skills)
  return stored.filter((id) => valid.has(id))
}

/** 按钮上显示已选 Skill 名称 */
export function skillTriggerLabel(skills: AgentSkill[], selectedIds: number[]): string {
  if (skills.length === 0) return 'Skill'
  if (selectedIds.length === 0) return '不使用 Skill'
  if (selectedIds.length === 1) {
    const hit = skills.find((skill) => skill.id === selectedIds[0])
    return hit?.name || 'Skill'
  }
  return `Skill · ${selectedIds.length}`
}
