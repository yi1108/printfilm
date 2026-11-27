export function studioGenerationError(value: unknown): string {
  const message = typeof value === 'string' ? value : ''
  const size = message.match(/expected the (height|width) to be at\s*least\s*(\d+)\s*px[\s\S]*?received\s*(?:a\s*)?(\d+)\s*[x×]\s*(\d+)\s*px/i)
  if (size) return `Seedance 参考图片尺寸不足。收到的图片为 ${size[3]} × ${size[4]} 像素，${size[1].toLowerCase() === 'height' ? '高度' : '宽度'}至少需要 ${size[2]} 像素。请更换该图片或等比放大后重试。`
  if (/at most one first[_ ]frame/i.test(message)) return '上次任务提交了多张首帧。图生视频只接受一张首帧；要指定结束画面请选择「首尾帧」，要参考多张图片请选择「全能参考」。'
  if (/ModelNotOpen|model.+not.+activated/i.test(message)) {
    const model = message.match(/(?:doubao-)?seedance-2[.-](?:0|5)(?:-fast)?(?:-\d{6})?/i)?.[0]
    const label = model ? `Seedance ${/2[.-]5/.test(model) ? '2.5' : '2.0'}${/-fast/i.test(model) ? ' Fast' : ''}` : '该次任务使用的模型'
    return `上次任务失败：当前供应商未开通${model ? ` ${label}` : label}。切换模型后请重新提交；此提示不代表当前所选模型的开通状态。`
  }
  if (/insufficient_quota|insufficient.balance|余额不足|欠费/i.test(message)) return '供应商余额或配额不足，请检查模型账户后重试。'
  if (/InvalidApiKey|Unauthorized|AuthenticationError|invalid.api.key/i.test(message)) return '供应商鉴权失败，请检查模型配置后重试。'
  if (/copyright restrictions/i.test(message)) {
    const requestId = message.match(/\brequest[ _-]?id\s*[:：]\s*([a-z0-9_-]{1,128})\b/i)?.[1]
    const explanation = '供应商判定生成的视频可能涉及版权限制，未返回视频。请检查提示词和参考素材是否包含第三方作品或角色，确认有使用授权后再提交。'
    return requestId ? `${explanation} 请求 ID：${requestId}` : explanation
  }
  if (/ContentPolicy|content.policy|sensitive|moderation/i.test(message)) return '供应商未通过内容审核，请调整提示词或参考素材后重试。'
  return message ? message.slice(0, 600) : '生成失败，请检查模型配置后重试。'
}
