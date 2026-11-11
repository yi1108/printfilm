export type ImageToolMode = 'mark' | 'lighting' | 'angle' | 'panorama'
export type ImageToolSettings = { yaw: number; pitch: number; brightness: number; color: string; distance: number; lens: number; panorama: 'sphere' | 'cylinder' }
export function imageToolPrompt(mode: ImageToolMode, settings: ImageToolSettings): string {
  const preserve = '以实际参考图为基础，保持已有主体的身份、外形、材质和场景一致，主体数量不变。'
  if (mode === 'lighting') return `${preserve}重新布光：主光水平角 ${settings.yaw}°（0°为正面，负数为画面左侧，±180°为背面），仰角 ${settings.pitch}°，亮度 ${settings.brightness}%，光线颜色 ${settings.color}。按照光源方向重建自然高光、阴影与反射，不改变构图。`
  if (mode === 'angle') return `${preserve}移动相机围绕主体拍摄，水平角 ${settings.yaw}°（0°为原视角，负数为主体左侧，±180°为背面），俯仰角 ${settings.pitch}°，距离 ${settings.distance} 米，${settings.lens}mm 镜头。重建该视角可见的三维结构，保持主体比例，不要仅旋转或翻转原图片。`
  return `${preserve}从固定相机位置重建并补全周围环境，输出一张连续的${settings.panorama === 'sphere' ? '720°球面等距柱状全景材质，严格2:1比例，覆盖360°经度和180°纬度，包含天顶和地面' : '360°水平柱面全景材质，严格4:1比例'}。地平线居中，左右边缘无缝衔接，不要拼格、边框、文字、相机、鱼眼或小行星效果。`
}

/** Map a rectilinear camera ray onto an equirectangular/cylindrical texture. */
export function panoramaUv(x: number, y: number, aspect: number, yaw: number, pitch: number, fov: number, cylinder = false): [number, number] {
  const rad = Math.PI / 180, scale = Math.tan(fov * rad / 2)
  const rx = x * scale * aspect, ry = -y * scale
  const cp = Math.cos(pitch * rad), sp = Math.sin(pitch * rad)
  const py = ry * cp + sp, pz = cp - ry * sp
  const longitude = Math.atan2(rx, pz) + yaw * rad
  const vertical = cylinder ? 2 * py / Math.hypot(rx, pz) / Math.PI : Math.atan2(py, Math.hypot(rx, pz)) / Math.PI
  return [((longitude / (2 * Math.PI) + .5) % 1 + 1) % 1, Math.max(0, Math.min(1, .5 - vertical))]
}
