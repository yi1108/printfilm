import type { DramaAsset } from '../api/drama'

/** 画布专用资产 type，不出现在全局/项目资产库列表 */
export const DRAMA_CANVAS_ONLY_ASSET_TYPES = new Set(['video', 'audio', 'text'])

/** 已停用的库类型（历史素材/none 不再展示） */
export const DRAMA_LIBRARY_DISABLED_TYPES = new Set(['material', 'none'])

// 判断资产是否应出现在资产库（角色/场景/道具/音色等）
export function isDramaLibraryAsset(asset: DramaAsset): boolean {
  const type = (asset.type || '').toLowerCase()
  if (DRAMA_CANVAS_ONLY_ASSET_TYPES.has(type)) return false
  if (DRAMA_LIBRARY_DISABLED_TYPES.has(type)) return false
  const assetType = (asset.asset_type || '').toLowerCase()
  if (assetType === 'video') return false
  return true
}

// 过滤出资产库可见项
export function filterDramaLibraryAssets(assets: DramaAsset[]): DramaAsset[] {
  return assets.filter(isDramaLibraryAsset)
}
