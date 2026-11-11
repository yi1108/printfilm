export function studioGenerationError(value: unknown): string {
  const message = typeof value === 'string' ? value : ''
  if (/ModelNotOpen|model.+not.+activated/i.test(message)) {
    const model = message.match(/(?:doubao-)?seedance-2[.-](?:0|5)(?:-fast)?(?:-\d{6})?/i)?.[0]
    const label = model ? `Seedance ${/2[.-]5/.test(model) ? '2.5' : '2.0'}${/-fast/i.test(model) ? ' Fast' : ''}` : '该次任务使用的模型'
    return `上次任务失败：当前供应商未开通${model ? ` ${label}` : label}。切换模型后请重新提交；此提示不代表当前所选模型的开通状态。`
  }
  if (/insufficient_quota|insufficient.balance|余额不足|欠费/i.test(message)) return '供应商余额或配额不足，请检查模型账户后重试。'
  if (/InvalidApiKey|Unauthorized|AuthenticationError|invalid.api.key/i.test(message)) return '供应商鉴权失败，请检查模型配置后重试。'
  if (/ContentPolicy|content.policy|sensitive|moderation/i.test(message)) return '供应商未通过内容审核，请调整提示词或参考素材后重试。'
  return message ? message.slice(0, 600) : '生成失败，请检查模型配置后重试。'
}
