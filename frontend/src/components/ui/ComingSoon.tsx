import { useI18n } from '../../i18n'

type Props = {
  label?: string
}

export default function ComingSoon({ label }: Props) {
  const { t } = useI18n()
  return <span className="pf-coming">{label || t('common.comingSoon')}</span>
}
