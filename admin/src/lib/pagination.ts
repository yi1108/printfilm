/** 模板列表每页数量（卡片网格铺满） */
export const TEMPLATE_PAGE_SIZE = 24;

/** Default page size for all admin list pages */
export const DEFAULT_PAGE_SIZE = 10;

/**
 * Build page number list with ellipsis markers
 * @param page current page (1-based)
 * @param totalPages total pages
 * @returns numbers and -1 for ellipsis
 */
export function buildPageItems(page: number, totalPages: number): number[] {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }
  const items: number[] = [1];
  const start = Math.max(2, page - 1);
  const end = Math.min(totalPages - 1, page + 1);
  if (start > 2) items.push(-1);
  for (let i = start; i <= end; i++) items.push(i);
  if (end < totalPages - 1) items.push(-1);
  items.push(totalPages);
  return items;
}
