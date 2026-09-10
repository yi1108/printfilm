import { useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import BrandMark from '../components/BrandMark'
import LanguageSwitch from '../components/layout/LanguageSwitch'
import { useI18n } from '../i18n'
import { isValidAuthPassword, isValidEmailInput } from '../lib/validateAuthForm'

type AuthMode = 'login' | 'register' | 'forgot' | 'reset'

// 仅允许站内相对路径回跳，防止开放重定向
function safeNextPath(raw: string | null, fallback = '/') {
  if (!raw) return fallback
  if (!raw.startsWith('/') || raw.startsWith('//') || raw.includes('://')) return fallback
  return raw
}

// 由 URL ?mode= / ?token= 决定初始 Auth 模式
function modeFromParams(params: URLSearchParams): AuthMode {
  const mode = (params.get('mode') || '').toLowerCase()
  if (mode === 'reset' || params.get('token')) return 'reset'
  if (mode === 'forgot') return 'forgot'
  if (mode === 'register') return 'register'
  return 'login'
}

export default function AuthPage() {
  const nav = useNavigate()
  const { t } = useI18n()
  const [params, setSearchParams] = useSearchParams()
  const nextPath = safeNextPath(params.get('next'), '/')
  /*
   * mode 当前表单模式
   * email / password / confirmPassword / nickname 表单字段
   * notice 成功提示（找回已发送、重置成功）
   * error / loading 提交态
   */
  const [mode, setMode] = useState<AuthMode>(() => modeFromParams(params))
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [nickname, setNickname] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(false)
  const resetToken = (params.get('token') || '').trim()

  // 切换模式并同步 URL（保留 next）
  function switchMode(next: AuthMode) {
    setMode(next)
    setError('')
    setNotice('')
    setPassword('')
    setConfirmPassword('')
    if (next === 'register') setNickname('')
    const nextParams = new URLSearchParams()
    if (nextPath && nextPath !== '/') nextParams.set('next', nextPath)
    if (next === 'forgot') nextParams.set('mode', 'forgot')
    else if (next === 'reset' && resetToken) {
      nextParams.set('mode', 'reset')
      nextParams.set('token', resetToken)
    } else if (next === 'register') nextParams.set('mode', 'register')
    setSearchParams(nextParams, { replace: true })
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setNotice('')

    if (mode === 'forgot') {
      const trimmedEmail = email.trim()
      if (!isValidEmailInput(trimmedEmail)) {
        setError(t('auth.emailInvalid'))
        return
      }
      setLoading(true)
      try {
        const res = await api.forgotPassword(trimmedEmail)
        setNotice(res.message || t('auth.forgotSent'))
      } catch (err) {
        setError(err instanceof Error ? err.message : t('common.fail'))
      } finally {
        setLoading(false)
      }
      return
    }

    if (mode === 'reset') {
      if (!resetToken) {
        setError(t('auth.resetTokenMissing'))
        return
      }
      if (!isValidAuthPassword(password)) {
        setError(password.length > 64 ? t('auth.passwordTooLong') : t('auth.passwordTooShort'))
        return
      }
      if (password !== confirmPassword) {
        setError(t('auth.passwordMismatch'))
        return
      }
      setLoading(true)
      try {
        await api.resetPassword(resetToken, password)
        setPassword('')
        setConfirmPassword('')
        switchMode('login')
        setNotice(t('auth.resetSuccess'))
      } catch (err) {
        setError(err instanceof Error ? err.message : t('common.fail'))
      } finally {
        setLoading(false)
      }
      return
    }

    const trimmedEmail = email.trim()
    if (mode === 'register' && !nickname.trim()) {
      setError(t('auth.nicknameRequired'))
      return
    }
    if (!isValidEmailInput(trimmedEmail)) {
      setError(t('auth.emailInvalid'))
      return
    }
    if (!isValidAuthPassword(password)) {
      setError(password.length > 64 ? t('auth.passwordTooLong') : t('auth.passwordTooShort'))
      return
    }

    setLoading(true)
    try {
      const res =
        mode === 'login'
          ? await api.login(trimmedEmail, password)
          : await api.register(trimmedEmail, password, nickname.trim())
      localStorage.setItem('token', res.access_token)
      nav(nextPath)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.fail'))
    } finally {
      setLoading(false)
    }
  }

  const title =
    mode === 'login'
      ? t('auth.loginTitle')
      : mode === 'register'
        ? t('auth.registerTitle')
        : mode === 'forgot'
          ? t('auth.forgotTitle')
          : t('auth.resetTitle')

  const submitLabel =
    mode === 'login'
      ? t('auth.login')
      : mode === 'register'
        ? t('auth.register')
        : mode === 'forgot'
          ? t('auth.sendReset')
          : t('auth.savePassword')

  return (
    <div className="auth-shell">
      <div className="auth-panel">
        <div className="auth-panel-top">
          <BrandMark />
          <LanguageSwitch />
        </div>
        <h1>{title}</h1>
        <form onSubmit={onSubmit} className="stack" noValidate>
          {mode === 'register' && (
            <label>
              {t('auth.nickname')}
              <input value={nickname} onChange={(e) => setNickname(e.target.value)} />
            </label>
          )}
          {(mode === 'login' || mode === 'register' || mode === 'forgot') && (
            <label>
              {t('auth.email')}
              <input
                type="email"
                inputMode="email"
                autoComplete="username"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value)
                  if (error) setError('')
                }}
              />
            </label>
          )}
          {(mode === 'login' || mode === 'register' || mode === 'reset') && (
            <label>
              {mode === 'reset' ? t('auth.newPassword') : t('auth.password')}
              <input
                type="password"
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value)
                  if (error) setError('')
                }}
              />
            </label>
          )}
          {mode === 'reset' && (
            <label>
              {t('auth.confirmPassword')}
              <input
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => {
                  setConfirmPassword(e.target.value)
                  if (error) setError('')
                }}
              />
            </label>
          )}
          {notice ? <p className="auth-notice" role="status">{notice}</p> : null}
          {error ? <p className="error" role="alert">{error}</p> : null}
          <button className="btn primary" disabled={loading}>
            {loading ? t('auth.processing') : submitLabel}
          </button>
        </form>
        {mode === 'login' && (
          <button type="button" className="linkish" onClick={() => switchMode('forgot')}>
            {t('auth.forgotLink')}
          </button>
        )}
        {(mode === 'login' || mode === 'register') && (
          <button
            type="button"
            className="linkish"
            onClick={() => switchMode(mode === 'login' ? 'register' : 'login')}
          >
            {mode === 'login' ? t('auth.toRegister') : t('auth.toLogin')}
          </button>
        )}
        {(mode === 'forgot' || mode === 'reset') && (
          <button type="button" className="linkish" onClick={() => switchMode('login')}>
            {t('auth.backToLogin')}
          </button>
        )}
      </div>
      <div className="auth-visual" aria-hidden>
        <div className="ink-wash" />
      </div>
    </div>
  )
}
