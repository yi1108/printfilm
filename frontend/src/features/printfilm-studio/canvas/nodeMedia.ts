/** Read a local image file into a data URL that can be stored with the canvas. */
export function fileToDataUrl(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('读取文件失败'))
    reader.onload = () => resolve(String(reader.result || ''))
    reader.readAsDataURL(file)
  })
}

/** Center-crop an image to the requested width/height ratio and return a PNG data URL. */
export function cropImageToDataUrl(src: string, ratio: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.crossOrigin = 'anonymous'
    image.onload = () => {
      try {
      const sourceRatio = image.width / image.height
      const cropWidth = sourceRatio > ratio ? image.height * ratio : image.width
      const cropHeight = sourceRatio > ratio ? image.height : image.width / ratio
      const canvas = document.createElement('canvas')
      canvas.width = Math.max(1, Math.round(cropWidth))
      canvas.height = Math.max(1, Math.round(cropHeight))
      const context = canvas.getContext('2d')
      if (!context) { reject(new Error('无法创建裁剪画布')); return }
      context.drawImage(image, (image.width - cropWidth) / 2, (image.height - cropHeight) / 2, cropWidth, cropHeight, 0, 0, canvas.width, canvas.height)
      resolve(canvas.toDataURL('image/png'))
      } catch { reject(new Error('无法裁剪此图片，请确认媒体存储允许跨域读取')) }
    }
    image.onerror = () => reject(new Error('图片无法裁剪，请确认图片地址可以访问'))
    image.src = src
  })
}
