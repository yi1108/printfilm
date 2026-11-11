import { marketText as mt } from './translate'
import { useMarketplaceLocale } from './useMarketplaceLocale'

export type AppEdition = 'domestic' | 'international'

export default function AppEditionPicker({ value, onChange }: { value: AppEdition[]; onChange: (value: AppEdition[]) => void }) {
  useMarketplaceLocale()
  return <fieldset><legend>{mt('App 投放版本')}<span className="pf-req-mark">{mt('必填')}</span></legend>
    <div className="pf-market-field-row">
      {(['domestic', 'international'] as const).map(edition => <label key={edition}>
        <input type="checkbox" checked={value.includes(edition)} onChange={event => onChange(event.target.checked ? [...value, edition] : value.filter(item => item !== edition))} />
        {mt(edition === 'domestic' ? '国内版' : '国际版')}
      </label>)}
    </div>
    <small>{mt('至少选择一个版本，同时勾选表示两版都投放。短剧所有分集继承系列设置。')}</small>
  </fieldset>
}
