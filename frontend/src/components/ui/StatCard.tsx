import type { ReactNode } from 'react'

type Props = {
  label: string
  value: string | number
  trend?: string
  icon?: ReactNode
}

export default function StatCard({ label, value, trend, icon }: Props) {
  return (
    <article className="pf-stat">
      <div className="pf-stat-top">
        {icon ? <span className="pf-stat-icon">{icon}</span> : null}
        <div className="label">{label}</div>
      </div>
      <div className="value">{value}</div>
      {trend ? <div className="trend">{trend}</div> : null}
    </article>
  )
}
