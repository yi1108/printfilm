type Step = {
  key: string
  label: string
}

type Props = {
  steps: Step[]
  current: number
  /** indices that are completed (0-based); defaults to all before current */
  doneThrough?: number
}

export default function Stepper({ steps, current, doneThrough }: Props) {
  const doneMax = doneThrough ?? current - 1
  return (
    <div className="pf-stepper" role="list">
      {steps.map((s, i) => {
        const done = i <= doneMax
        const active = i === current
        return (
          <div key={s.key} className="pf-stepper" role="listitem">
            {i > 0 ? <span className={done || active ? 'pf-step-line done' : 'pf-step-line'} /> : null}
            <span className={['pf-step', done ? 'done' : '', active ? 'active' : ''].filter(Boolean).join(' ')}>
              <span className="pf-step-dot">{done && !active ? '✓' : i + 1}</span>
              {s.label}
            </span>
          </div>
        )
      })}
    </div>
  )
}
