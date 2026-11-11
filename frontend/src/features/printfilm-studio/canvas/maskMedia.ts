import { compositeMaskPixels, validateInpaintAspect } from './maskPixels'
export type InpaintData = { originalUrl: string; maskUrl: string; guideUrl: string }

export async function readCanvasImage(url: string) {
  const image = new Image(); image.crossOrigin = 'anonymous'; image.src = url
  await image.decode().catch(() => { throw new Error('图片无法读取，请确认素材地址及跨域配置') })
  if (!image.naturalWidth || image.naturalWidth * image.naturalHeight > 16_777_216) throw new Error('编辑图片不能超过 1600 万像素')
  return image
}
export const canvasBlob = (canvas: HTMLCanvasElement) => new Promise<Blob>((resolve, reject) => {
  try { canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('图片编码失败')), 'image/png') }
  catch { reject(new Error('图片不允许跨域编辑，请先导入为项目素材')) }
})

export async function finishInpaint(data: InpaintData, generatedUrl: string) {
  const [original, mask, generated] = await Promise.all([readCanvasImage(data.originalUrl), readCanvasImage(data.maskUrl), readCanvasImage(generatedUrl)])
  if (mask.naturalWidth !== original.naturalWidth || mask.naturalHeight !== original.naturalHeight) throw new Error('蒙版尺寸不匹配，请重新绘制')
  validateInpaintAspect(original.naturalWidth, original.naturalHeight, generated.naturalWidth, generated.naturalHeight)
  const canvas = document.createElement('canvas'); canvas.width = original.naturalWidth; canvas.height = original.naturalHeight
  const ctx = canvas.getContext('2d', { willReadFrequently: true })!
  const pixels = (image: HTMLImageElement) => { ctx.clearRect(0, 0, canvas.width, canvas.height); ctx.drawImage(image, 0, 0, canvas.width, canvas.height); return ctx.getImageData(0, 0, canvas.width, canvas.height).data }
  const result = compositeMaskPixels(pixels(original), pixels(generated), pixels(mask))
  ctx.putImageData(new ImageData(result, canvas.width, canvas.height), 0, 0)
  return canvasBlob(canvas)
}
