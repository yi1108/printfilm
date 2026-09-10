/** 安全页：当前密码 + 新密码确认后提交修改 */
import { useState, type FormEvent } from 'react'
import { api } from '../../api'
import { useI18n } from '../../i18n'

type Props = {
  email: string
}

// 渲染修改密码表单
export default function ChangePasswordCard({ email }: Props) {
  const { t } = useI18n()
  /*
   * currentPassword 当前密码
   * newPassword 新密码
   * confirmPassword 确认新密码
   * busy 提交中
   * error 错误文案
   * ok 成功提示
   */
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [ok, setOk] = useState(false)

  const canSubmit =
    !busy &&
    currentPassword.length > 0 &&
    newPassword.length >= 6 &&
    newPassword.length <= 64 &&
    newPassword === confirmPassword

  // 校验并提交修改密码
  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (busy) return
    setError('')
    setOk(false)
    if (newPassword.length < 6) {
      setError(t('settings.passwordTooShort'))
      return
    }
    if (newPassword !== confirmPassword) {
      setError(t('settings.passwordMismatch'))
      return
    }
    if (newPassword === currentPassword) {
      setError(t('settings.passwordSameAsOld'))
      return
    }
    setBusy(true)
    try {
      await api.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      })
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setOk(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.passwordChangeFailed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="pf-settings-card">
      <h1>{t('settings.tabs.security')}</h1>
      <p className="pf-muted">{t('settings.securityLead')}</p>
      <div className="pf-settings-fields">
        <label>
          <span>{t('settings.loginEmail')}</span>
          <input value={email} readOnly autoComplete="username" />
        </label>
      </div>
      <form className="pf-settings-fields" onSubmit={(e) => void handleSubmit(e)}>
        <label>
          <span>{t('settings.currentPassword')}</span>
          <input
            type="password"
            value={currentPassword}
            autoComplete="current-password"
            onChange={(e) => {
              setCurrentPassword(e.target.value)
              setOk(false)
            }}
          />
        </label>
        <label>
          <span>{t('settings.newPassword')}</span>
          <input
            type="password"
            value={newPassword}
            autoComplete="new-password"
            minLength={6}
            maxLength={64}
            onChange={(e) => {
              setNewPassword(e.target.value)
              setOk(false)
            }}
          />
          <em className="pf-muted">{t('settings.passwordHint')}</em>
        </label>
        <label>
          <span>{t('settings.confirmPassword')}</span>
          <input
            type="password"
            value={confirmPassword}
            autoComplete="new-password"
            minLength={6}
            maxLength={64}
            onChange={(e) => {
              setConfirmPassword(e.target.value)
              setOk(false)
            }}
          />
        </label>
        {error ? <p className="pf-error">{error}</p> : null}
        {ok ? <p className="pf-muted">{t('settings.passwordChanged')}</p> : null}
        <div className="pf-settings-actions">
          <button type="submit" className="pf-btn pf-btn-lime pf-btn-sm" disabled={!canSubmit}>
            {busy ? t('common.saving') : t('settings.changePassword')}
          </button>
        </div>
      </form>
    </section>
  )
}
