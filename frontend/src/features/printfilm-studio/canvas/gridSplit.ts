export function gridTiles(width: number, height: number, rows: number, columns: number) {
  if (![width, height, rows, columns].every(Number.isInteger) || width < columns || height < rows || rows < 1 || columns < 1 || rows > 10 || columns > 10 || rows * columns < 2) throw new Error('请设置 1–10 行、1–10 列，至少切成两张图片')
  return Array.from({ length: rows * columns }, (_, index) => {
    const row = Math.floor(index / columns), column = index % columns
    const x = Math.floor(column * width / columns), y = Math.floor(row * height / rows)
    return { row, column, x, y, width: Math.floor((column + 1) * width / columns) - x, height: Math.floor((row + 1) * height / rows) - y }
  })
}
