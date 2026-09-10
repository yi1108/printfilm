/** Drama project workflow steps (aligned with manju projectSteps). */

export type ProjectStepKey = 'outline' | 'assets' | 'episodes'

export type ProjectStepItem = {
  key: ProjectStepKey
  label: string
  order: number
}

export function buildProjectSteps(hasScript: boolean): ProjectStepItem[] {
  const steps: Array<{ key: ProjectStepKey; label: string }> = hasScript
    ? [
        { key: 'outline', label: '剧情大纲' },
        { key: 'assets', label: '资产库' },
        { key: 'episodes', label: '分集视频' },
      ]
    : [
        { key: 'assets', label: '资产库' },
        { key: 'episodes', label: '分集视频' },
      ]
  return steps.map((step, index) => ({ ...step, order: index + 1 }))
}

export function getInitialProjectStep(hasScript: boolean): ProjectStepKey {
  return hasScript ? 'outline' : 'assets'
}

export function getNextProjectStep(
  steps: ProjectStepItem[],
  currentStep: ProjectStepKey,
): ProjectStepKey | null {
  const currentIndex = steps.findIndex((step) => step.key === currentStep)
  if (currentIndex < 0 || currentIndex >= steps.length - 1) return null
  return steps[currentIndex + 1].key
}
