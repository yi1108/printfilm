import { useEffect, useState } from 'react'
import { apiKeysApi, getPublicApiBase, type ApiKeyItem } from '../../api/apiKeys'
import { dialog } from '../../lib/dialog'

/** 格式化时间 */
function formatWhen(iso?: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** 设置页 API：Key 管理与调用文档 */
export default function ApiKeysPanel() {
  /*
   * keys Key 列表
   * name 新建名称
   * busy 提交中
   * error 错误
   * createdSecret 刚创建的一次性 secret
   */
  const [keys, setKeys] = useState<ApiKeyItem[]>([])
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [createdSecret, setCreatedSecret] = useState('')

  const base = getPublicApiBase()

  async function reload() {
    setError('')
    try {
      setKeys(await apiKeysApi.list())
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败')
    }
  }

  useEffect(() => {
    void reload()
  }, [])

  async function handleCreate() {
    if (busy) return
    setBusy(true)
    setError('')
    setCreatedSecret('')
    try {
      const row = await apiKeysApi.create(name.trim() || '默认 Key')
      setCreatedSecret(row.secret)
      setName('')
      await reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建失败')
    } finally {
      setBusy(false)
    }
  }

  async function handleRevoke(item: ApiKeyItem) {
    const ok = await dialog.confirm({
      title: '撤销 API Key',
      message: `确定撤销「${item.name}」（${item.key_prefix}…）？撤销后无法恢复。`,
      confirmText: '撤销',
    })
    if (!ok) return
    setBusy(true)
    setError('')
    try {
      await apiKeysApi.revoke(item.id)
      await reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : '撤销失败')
    } finally {
      setBusy(false)
    }
  }

  async function copyText(text: string) {
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      /* ignore */
    }
  }

  return (
    <section className="pf-settings-card">
      <h1>API</h1>
      <p className="pf-muted">使用 API Key 调用生图、生视频与 Seedance 转发，按量从余额扣费</p>

      <div className="pf-api-create">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Key 名称，如「生产环境」"
          maxLength={64}
        />
        <button type="button" className="pf-btn pf-btn-lime pf-btn-sm" disabled={busy} onClick={() => void handleCreate()}>
          {busy ? '处理中…' : '创建 Key'}
        </button>
      </div>

      {createdSecret ? (
        <div className="pf-api-secret">
          <p>
            <strong>请立即复制保存，关闭后无法再次查看：</strong>
          </p>
          <code>{createdSecret}</code>
          <button type="button" className="pf-btn pf-btn-ghost pf-btn-sm" onClick={() => void copyText(createdSecret)}>
            复制 Key
          </button>
        </div>
      ) : null}

      {error ? <p className="pf-error">{error}</p> : null}

      {keys.length > 0 ? (
        <ul className="pf-settings-list pf-api-key-list">
          {keys.map((item) => (
            <li key={item.id}>
              <div className="pf-settings-list-row">
                <span className="pf-settings-list-main">
                  <strong>{item.name}</strong>
                  <em className="pf-muted">
                    {item.key_prefix}… · 创建于 {formatWhen(item.created_at)}
                    {item.last_used_at ? ` · 最近使用 ${formatWhen(item.last_used_at)}` : ''}
                  </em>
                </span>
                <button
                  type="button"
                  className="pf-btn pf-btn-ghost pf-btn-sm"
                  disabled={busy}
                  onClick={() => void handleRevoke(item)}
                >
                  撤销
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <div className="pf-settings-empty">
          <p>还没有 API Key</p>
        </div>
      )}

      <div className="pf-api-docs">
        <h3>调用说明</h3>
        <p className="pf-muted">鉴权：Header 任选其一</p>
        <pre>{`Authorization: Bearer pf_live_...\nX-Api-Key: pf_live_...`}</pre>

        <p className="pf-muted">生图（Seedream）</p>
        <pre>{`POST ${base}/api/v1/images/generations
Content-Type: application/json

{
  "prompt": "赛博朋克城市夜景",
  "ratio": "16:9",
  "image_url": null
}`}</pre>

        <p className="pf-muted">生视频（Seedance 首帧图生视频）</p>
        <pre>{`POST ${base}/api/v1/videos/generations

{
  "prompt": "镜头缓慢推进，霓虹闪烁",
  "image_url": "https://.../first_frame.jpg",
  "duration": 5,
  "resolution": "480p"
}`}</pre>

        <p className="pf-muted">Seedance 转发（多模态 body）</p>
        <pre>{`POST ${base}/api/v1/seedance/tasks

{
  "content": [
    { "type": "text", "text": "描述..." },
    { "type": "image_url", "image_url": { "url": "https://..." }, "role": "first_frame" }
  ],
  "duration": 5,
  "resolution": "480p"
}`}</pre>

        <p className="pf-muted">查询视频任务</p>
        <pre>{`GET ${base}/api/v1/tasks/{task_id}`}</pre>
      </div>
    </section>
  )
}
