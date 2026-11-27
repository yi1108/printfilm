export function isSeedanceVideoModel(model: unknown) {
  return /^(?:doubao-)?seedance(?:[.-]|$)/i.test(String(model ?? ''))
}

export function seedanceImageHeightError(name: string, width: number, height: number) {
  return height > 0 && height < 300
    ? `「${name}」的尺寸为 ${width} × ${height} 像素。Seedance 要求图片高度至少为 300 像素，请更换图片或等比放大后重试。`
    : undefined
}

export async function seedanceReferenceImageError(source: string | File, name: string) {
  const local = typeof source !== 'string'
  const url = local ? URL.createObjectURL(source) : source
  try {
    const image = new Image()
    image.src = url
    await image.decode()
    return seedanceImageHeightError(name, image.naturalWidth, image.naturalHeight)
  } catch {
    // The provider may be able to read a saved asset the browser cannot preview.
    return local ? `无法读取「${name}」的图片尺寸，请重新选择有效的图片。` : undefined
  } finally {
    if (local) URL.revokeObjectURL(url)
  }
}
