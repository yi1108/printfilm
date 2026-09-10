import type { Locale } from './detect'
import { en } from './locales/en'
import { zh } from './locales/zh'

export type Messages = typeof zh

export const messages: Record<Locale, Messages> = {
  zh,
  en: en as unknown as Messages,
}
