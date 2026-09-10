import { Navigate, useSearchParams } from 'react-router-dom'

/** Legacy `/studio` entry — redirect to multi-step routes. */
export default function StudioPage() {
  const [params] = useSearchParams()
  const project = params.get('project')
  const template = params.get('template')
  const mode = params.get('mode')

  if (project) {
    return <Navigate to={`/studio/${project}`} replace />
  }

  const q = new URLSearchParams()
  if (template) q.set('template', template)
  if (mode) q.set('mode', mode)
  const qs = q.toString()
  return <Navigate to={qs ? `/studio/new?${qs}` : '/studio/new'} replace />
}
