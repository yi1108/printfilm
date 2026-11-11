export class InpaintAspectMismatchError extends Error {}

export function validateInpaintAspect(originalWidth: number, originalHeight: number, generatedWidth: number, generatedHeight: number) {
  const originalRatio = originalWidth / originalHeight
  const generatedRatio = generatedWidth / generatedHeight
  if (![originalWidth, originalHeight, generatedWidth, generatedHeight].every((value) => Number.isFinite(value) && value > 0)
    || Math.abs(generatedRatio / originalRatio - 1) > .02) {
    throw new InpaintAspectMismatchError('模型返回的画幅与原图不一致，已停止合成以避免变形。原图已保留，请选择支持原图画幅的模型后重试。')
  }
}

/** Alpha compositing in straight RGBA; unselected pixels remain byte-identical. */
export function compositeMaskPixels(original: Uint8ClampedArray, generated: Uint8ClampedArray, mask: Uint8ClampedArray) {
  if (original.length !== generated.length || mask.length !== original.length || original.length % 4) throw new Error('蒙版与图片尺寸不一致')
  const result = original.slice()
  for (let i = 0; i < result.length; i += 4) {
    const strength = mask[i + 3] / 255
    if (!strength) continue
    const fg = generated[i + 3] / 255 * strength
    const bg = original[i + 3] / 255 * (1 - fg)
    const alpha = fg + bg
    for (let channel = 0; channel < 3; channel++) result[i + channel] = alpha ? (generated[i + channel] * fg + original[i + channel] * bg) / alpha : 0
    result[i + 3] = alpha * 255
  }
  return result
}
