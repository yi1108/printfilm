/** 全局分页默认每页条数选项 */
export const DEFAULT_PAGE_SIZE_OPTIONS = [5, 8, 12, 20] as const

/** 根据总数与每页条数计算页数 */
export function pageCountOf(total: number, pageSize: number) {
  return Math.max(1, Math.ceil(Math.max(0, total) / Math.max(1, pageSize)))
}
