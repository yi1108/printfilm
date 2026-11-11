import { zhPages } from './zh/pages'
import { zhShell } from './zh/shell'
import { zhShortVideoCreate } from './zh/shortVideoCreate'

export const zh = {
  ...zhShell,
  ...zhPages,
  shortVideoCreate: zhShortVideoCreate,
}
