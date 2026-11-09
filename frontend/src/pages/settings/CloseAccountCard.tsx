import { useEffect, useRef, useState, type FormEvent } from 'react'
import { TriangleAlert } from 'lucide-react'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { USER_UPDATED_EVENT } from '../../lib/userEvents'

/** 提供不可逆账号注销的密码校验、明确确认和结果反馈。 */
export default function CloseAccountCard() {
  const { t } = useI18n()
  // 敏感输入只保留在当前组件内，成功后立即清空。
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [succeeded, setSucceeded] = useState(false)
  const redirectTimer = useRef<number | undefined>(undefined)
  const confirmationWord = t('settings.closeConfirmationWord')

  /** 页面提前离开时取消尚未执行的跳转。 */
  useEffect(() => () => window.clearTimeout(redirectTimer.current), [])

  /** 提交注销请求；服务端成功后才清除本地登录态并广播。 */
  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (confirmation !== confirmationWord || busy) return
    setError('')
    setBusy(true)
    try {
      await api.closeAccount({ password, confirmation })
      setPassword('')
      setConfirmation('')
      setSucceeded(true)
      localStorage.removeItem('token')
      window.dispatchEvent(new Event(USER_UPDATED_EVENT))
      redirectTimer.current = window.setTimeout(() => window.location.assign('/'), 900)
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : t('settings.closeAccountFailed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="pf-close-account-card" aria-labelledby="close-account-title">
      <div className="pf-close-account-heading">
        <TriangleAlert size={20} aria-hidden="true" />
        <div>
          <h2 id="close-account-title">{t('settings.requestDelete')}</h2>
          <p className="pf-muted">{t('settings.closeAccountLead')}</p>
        </div>
      </div>
      <div className="pf-close-account-notice">
        <p>{t('settings.closeAccountWarning')}</p>
        <p>{t('settings.closeAccountRetention')}</p>
        <p>{t('settings.closeAccountBlockers')}</p>
      </div>
      <form onSubmit={handleSubmit}>
        <div className="pf-settings-fields">
          <label htmlFor="close-account-password">
            <span>{t('settings.closeAccountPassword')}</span>
            <input
              id="close-account-password"
              type="password"
              autoComplete="current-password"
              minLength={1}
              maxLength={64}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={busy || succeeded}
              required
            />
          </label>
          <label htmlFor="close-account-confirmation">
            <span>{t('settings.closeAccountConfirmation')}</span>
            <input
              id="close-account-confirmation"
              type="text"
              autoComplete="off"
              spellCheck={false}
              maxLength={16}
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              disabled={busy || succeeded}
              required
              aria-describedby="close-account-confirmation-hint"
            />
            <em id="close-account-confirmation-hint" className="pf-muted">
              {t('settings.closeAccountConfirmation')}
            </em>
          </label>
        </div>
        {error && <p className="pf-error" role="alert">{error}</p>}
        {succeeded && <p className="pf-close-account-success" role="status">{t('settings.closeAccountSuccess')}</p>}
        <div className="pf-settings-actions">
          <button
            type="submit"
            className="pf-btn pf-btn-danger"
            disabled={busy || succeeded || !password || confirmation !== confirmationWord}
          >
            {busy ? t('settings.closeAccountBusy') : t('settings.closeAccountSubmit')}
          </button>
        </div>
      </form>
    </section>
  )
}
