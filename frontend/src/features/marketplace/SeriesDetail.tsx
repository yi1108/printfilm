import { useMarketplaceLocale } from './useMarketplaceLocale'
import { marketText as mt, marketFeedback } from './translate'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Lock } from 'lucide-react'
import { Contact, Media, NeedLogin } from './shared'
import { money, request, type Row } from './api'
import { PageHeading } from './ui'
import { isFreeEpisode } from './playbackPolicy'

type Episode = Row & { episode_no: number; description?: string }
type Series = { id: number; title: string; description?: string; category?: string; category_label?: string; sale_type: string; copyright_price_fen?: number; free_episode_count?: number; episodes: Episode[] }

const pageSize = 15

function rememberKey(id: number) {
  return `pf-market-series-${id}`
}

// 短剧详情只挂一个播放器，选集格切换当前集。
export default function SeriesDetail() {
  const locale = useMarketplaceLocale()
  const id = Number(useParams().id)
  const [item, setItem] = useState<Series | null>(null)
  const [error, setError] = useState('')
  const [current, setCurrent] = useState(1)
  const [range, setRange] = useState(0)
  const [autoPlay, setAutoPlay] = useState(false)
  useEffect(() => {
    let active = true
    request<Series>(`/series/${id}`).then(value => {
      if (!active) return
      const saved = Number(sessionStorage.getItem(rememberKey(id)) || 1)
      const episode = value.episodes.find(entry => entry.episode_no === saved) || value.episodes[0]
      setItem(value)
      if (episode) {
        setCurrent(episode.episode_no)
        setRange(Math.floor((episode.episode_no - 1) / pageSize))
      }
    }).catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [id, locale])
  function select(episodeNo: number, play = true) {
    setCurrent(episodeNo)
    setAutoPlay(play)
    setRange(Math.floor((episodeNo - 1) / pageSize))
    sessionStorage.setItem(rememberKey(id), String(episodeNo))
  }
  if (error) return <p role="alert">{marketFeedback(error)}</p>
  if (!item) return <p role="status">{mt("正在加载短剧…")}</p>
  const episode = item.episodes.find(entry => entry.episode_no === current) || item.episodes[0]
  if (!episode) return <p>{mt("这部短剧还没有可播放的分集。")}</p>
  const free = isFreeEpisode(item, episode.episode_no)
  const index = item.episodes.findIndex(entry => entry.id === episode.id)
  const previous = item.episodes[index - 1]
  const next = item.episodes[index + 1]
  const ranges = Math.ceil(item.episodes.length / pageSize)
  const visible = item.episodes.filter(entry => Math.floor((entry.episode_no - 1) / pageSize) === range)
  const price = item.sale_type === 'platform_unlock' ? mt("按集解锁") : mt("版权合作参考价 {0}", [money(item.copyright_price_fen)])
  return <>
    <PageHeading title={item.title} description={mt("{0} · 短剧 · {1} 集", [item.category_label || item.category || mt('其他'), item.episodes.length])} back="/marketplace" />
    <div className="pf-series-layout">
      <section className="pf-series-stage">
        <Media key={episode.id} kind="series_episode" id={episode.id} purpose="preview" video autoPlay={autoPlay} onEnded={() => { if (next) select(next.episode_no) }} />
      </section>
      <aside className="pf-series-side">
        <section className="pf-series-meta">
          <p>{item.sale_type === 'free' || (item.free_episode_count || 0) >= item.episodes.length ? mt("全部免费，播放原片") : (item.free_episode_count || 0) > 0 ? mt("前 {0} 集免费播放原片，之后 {1}", [item.free_episode_count, price]) : `${item.sale_type === 'platform_unlock' ? mt("平台投放收益") : mt("版权出售收益")} · ${price}`}</p>
          <p className="pf-market-text">{item.description || mt("暂无系列简介")}</p>
          <p>{free ? mt("本集免费观看，直接播放原片。使用仍须遵守作者授权范围。") : item.sale_type === 'platform_unlock' ? mt("未购买时可看短试看，购买后可永久在线播放所购版本，不包含版权转让。") : mt("当前提供短试看。版权合作请联系客服，确认价格、授权或转让范围及完整成片交付。")}</p>
          {!free && <small>{mt("短试看不加水印，最长15秒且不超过原片时长的30%。")}</small>}
          {!free && item.sale_type === 'copyright_contact' && <NeedLogin><Contact kind="series_episode" id={episode.id} /></NeedLogin>}
          {!free && item.sale_type === 'platform_unlock' && <small>{mt("当前网页仅提供短试看，暂不支持购买和完整播放。")}</small>}
        </section>
        <div className="pf-series-transport">
          <button type="button" disabled={!previous} onClick={() => previous && select(previous.episode_no)}>{mt("上一集")}</button>
          <span>{mt("第")} {episode.episode_no}  {mt("集 ·")} {episode.title}</span>
          <button type="button" disabled={!next} onClick={() => next && select(next.episode_no)}>{mt("下一集")}</button>
        </div>
        <section className="pf-series-picker" aria-label={mt("选集")}>
          {ranges > 1 && <div className="pf-series-ranges">{Array.from({ length: ranges }, (_, group) => {
            const start = group * pageSize + 1
            const end = Math.min(item.episodes.length, start + pageSize - 1)
            return <button key={group} type="button" aria-pressed={group === range} onClick={() => setRange(group)}>{start}–{end}</button>
          })}</div>}
          <div className="pf-series-grid">{visible.map(entry => {
            const locked = !isFreeEpisode(item, entry.episode_no)
            return <button key={entry.id} type="button" className={entry.episode_no === episode.episode_no ? 'is-current' : ''} aria-current={entry.episode_no === episode.episode_no} onClick={() => select(entry.episode_no)}>{entry.episode_no}{locked && <Lock size={12} aria-label={mt("收费")} />}</button>
          })}</div>
        </section>
      </aside>
    </div>
    <Link to="/marketplace">{mt("返回作品广场")}</Link>
  </>
}
