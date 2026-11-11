import type { ReactNode } from 'react'
import './workspaceToolbar.css'

/** Shared canvas/storyboard action bar; callers only control placement and actions. */
export function WorkspaceToolbar({ children, label, className = '' }: { children: ReactNode; label: string; className?: string }) {
  return <div className={`pf-workspace-toolbar ${className}`} role="group" aria-label={label}>{children}</div>
}
