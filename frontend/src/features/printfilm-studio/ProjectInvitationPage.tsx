import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import AppShell from '../../components/layout/AppShell'
import Button from '../../components/ui/Button'
import { projectSharingApi } from './projectSharing'

/** Invitation secrets stay in the fragment and are submitted only in a POST body. */
export default function ProjectInvitationPage() {
  const location = useLocation(), navigate = useNavigate()
  const [token] = useState(() => {
    const incoming = new URLSearchParams(location.hash.slice(1)).get('token')
    if (incoming) return incoming
    const pending = sessionStorage.getItem('pf-project-invite')
    if (!pending) return ''
    try { const item = JSON.parse(pending); return item.expires > Date.now() ? String(item.token) : '' } catch { return '' }
  })
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const loggedIn = Boolean(localStorage.getItem('token'))
  async function accept() {
    setBusy(true); setError('')
    try {
      const result = await projectSharingApi.accept(token)
      sessionStorage.removeItem('pf-project-invite')
      navigate(`/drama/projects/${result.project_id}/canvas`, { replace: true })
    } catch (cause) { setError(cause instanceof Error ? cause.message : '加入失败，请重试') } finally { setBusy(false) }
  }
  function login() {
    sessionStorage.setItem('pf-project-invite', JSON.stringify({ token, expires: Date.now() + 30 * 60_000 }))
    navigate('/auth?next=%2Fcanvas%2Fjoin', { replace: true })
  }
  return <AppShell active="canvas"><section className="pf-team-panel pf-team-empty"><h1>加入项目团队</h1><p>加入后可以与项目成员一起编辑画布、查看素材和生成结果。</p><p>生成费用由实际点击生成的成员个人承担。</p>{token ? <Button variant="lime" disabled={busy} onClick={() => loggedIn ? void accept() : login()}>{busy ? '正在加入…' : loggedIn ? '接受邀请并加入项目' : '登录后加入项目'}</Button> : <p role="alert">缺少有效邀请链接，请向项目所有者获取。</p>}{error && <p role="alert">{error}</p>}<Button to="/canvas">返回项目列表</Button></section></AppShell>
}
