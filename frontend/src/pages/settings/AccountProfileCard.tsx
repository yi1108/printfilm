import { useEffect, useRef, useState } from 'react'
import UserAvatar from '../../components/UserAvatar'
import ComingSoon from '../../components/ui/ComingSoon'
import LanguageSwitch from '../../components/layout/LanguageSwitch'
import { api, type User } from '../../api'
import { dispatchUserUpdated } from '../../lib/userEvents'
import { useI18n } from '../../i18n'

type AccountProfileCardProps = {
  user: User | null
  onUserChange: (user: User) => void
}

/** 账号资料：头像、用户名、邮箱、手机号（手机号仅记录） */
export default function AccountProfileCard({ user, onUserChange }: AccountProfileCardProps) {
  const { t } = useI18n()
  /*
   * nickname / email / phone 表单值
   * saveBusy 保存中
   * saveError 保存失败
   * saveOk 保存成功提示
   * avatarBusy 头像上传中
   * avatarError 头像失败原因
   */
  const [nickname, setNickname] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [saveBusy, setSaveBusy] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [saveOk, setSaveOk] = useState(false)
  const [avatarBusy, setAvatarBusy] = useState(false)
  const [avatarError, setAvatarError] = useState('')
  const avatarInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!user) return
    setNickname(user.nickname || '')
    setEmail(user.email || '')
    setPhone(user.phone || '')
  }, [user])

  const dirty =
    !!user &&
    (nickname.trim() !== (user.nickname || '') ||
      email.trim() !== (user.email || '') ||
      phone.trim() !== (user.phone || ''))

  // 选择并上传头像
  async function handleAvatarChange(file: File | undefined) {
    if (!file || avatarBusy) return
    setAvatarError('')
    setAvatarBusy(true)
    try {
      const updated = await api.uploadAvatar(file)
      onUserChange(updated)
      dispatchUserUpdated(updated)
    } catch (e) {
      setAvatarError(e instanceof Error ? e.message : t('settings.avatarFailed'))
    } finally {
      setAvatarBusy(false)
      if (avatarInputRef.current) avatarInputRef.current.value = ''
    }
  }

  // 保存用户名、邮箱、手机号
  async function handleSave() {
    if (!user || saveBusy) return
    setSaveError('')
    setSaveOk(false)
    setSaveBusy(true)
    try {
      const updated = await api.updateProfile({
        nickname: nickname.trim(),
        email: email.trim(),
        phone: phone.trim(),
      })
      onUserChange(updated)
      dispatchUserUpdated(updated)
      setSaveOk(true)
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : t('settings.saveFailed'))
    } finally {
      setSaveBusy(false)
    }
  }

  return (
    <section className="pf-settings-card">
      <h1>{t('settings.tabs.account')}</h1>
      <p className="pf-muted">{t('settings.accountLead')}</p>
      <div className="pf-settings-avatar-row">
        <UserAvatar user={user} size="xl" />
        <div className="pf-settings-avatar-actions">
          <p className="pf-muted">{t('settings.avatarHint')}</p>
          <div className="pf-settings-actions">
            <button
              type="button"
              className="pf-btn pf-btn-lime pf-btn-sm"
              disabled={avatarBusy}
              onClick={() => avatarInputRef.current?.click()}
            >
              {avatarBusy ? t('settings.uploading') : user?.avatar_url ? t('settings.changeAvatar') : t('settings.uploadAvatar')}
            </button>
          </div>
          {avatarError ? <p className="pf-error">{avatarError}</p> : null}
          <input
            ref={avatarInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,image/gif"
            hidden
            onChange={(e) => void handleAvatarChange(e.target.files?.[0])}
          />
        </div>
      </div>
      <div className="pf-settings-fields">
        <label>
          <span>{t('settings.nickname')}</span>
          <input
            value={nickname}
            maxLength={64}
            autoComplete="nickname"
            onChange={(e) => {
              setNickname(e.target.value)
              setSaveOk(false)
            }}
          />
        </label>
        <label>
          <span>{t('settings.email')}</span>
          <input
            type="email"
            value={email}
            autoComplete="email"
            onChange={(e) => {
              setEmail(e.target.value)
              setSaveOk(false)
            }}
          />
        </label>
        <label>
          <span>{t('settings.phone')}</span>
          <input
            type="tel"
            value={phone}
            inputMode="numeric"
            autoComplete="tel"
            placeholder={t('settings.phonePlaceholder')}
            onChange={(e) => {
              setPhone(e.target.value)
              setSaveOk(false)
            }}
          />
          <em className="pf-muted">{t('settings.phoneHint')}</em>
        </label>
        <label>
          <span>{t('settings.language')}</span>
          <div className="pf-settings-lang">
            <LanguageSwitch />
            <em className="pf-muted">{t('settings.languageHint')}</em>
          </div>
        </label>
      </div>
      {saveError ? <p className="pf-error">{saveError}</p> : null}
      {saveOk ? <p className="pf-muted">{t('common.saved')}</p> : null}
      <div className="pf-settings-actions">
        <button
          type="button"
          className="pf-btn pf-btn-lime pf-btn-sm"
          disabled={!user || saveBusy || !dirty}
          onClick={() => void handleSave()}
        >
          {saveBusy ? t('common.saving') : t('settings.saveProfile')}
        </button>
        <button type="button" className="pf-btn pf-btn-ghost pf-btn-sm" disabled>
          {t('settings.requestDelete')} <ComingSoon />
        </button>
      </div>
    </section>
  )
}
