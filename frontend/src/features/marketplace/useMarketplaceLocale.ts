import { useI18n } from '../../i18n'

/** 订阅现有全站语言；不重挂组件，因此草稿、上传和签名状态得以保留。 */
export function useMarketplaceLocale() {
  return useI18n().locale
}
