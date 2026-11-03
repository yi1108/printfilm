import { useMarketplaceLocale } from './useMarketplaceLocale'
import { marketText as mt } from './translate'
import { Navigate, Route, Routes } from 'react-router-dom'
import AppShell from '../../components/layout/AppShell'
import { Gate, NeedLogin } from './shared'
import Gallery from './Gallery'
import WorkEditor from './WorkEditor'
import RecruitEditor from './RecruitEditor'
import Detail from './Detail'
import Workspace from './Workspace'
import RightsPage from './RightsPage'
import AuthorizationPanel from './AuthorizationPanel'
import SeriesEditor from './SeriesEditor'
import SeriesDetail from './SeriesDetail'
import FromPrintfilm from './FromPrintfilm'
import './marketplace.css'

// 独立下游路由壳；不替换原 studio、作品或个人设置页面。
export default function Marketplace() {
  const locale = useMarketplaceLocale()
  return <div className="pf-market-shell" lang={locale === 'en' ? 'en' : 'zh-CN'}><AppShell wide><div className="pf-market"><Gate><Routes>
    <Route index element={<Gallery key="works" />} /><Route path="recruits" element={<Gallery key="recruits" recruits />} />
    <Route path="series" element={<Navigate to="/marketplace" replace />} />
    <Route path="series/new" element={<Navigate to="/marketplace/works/new?type=series" replace />} />
    <Route path="series/:id" element={<SeriesDetail />} />
    <Route path="works/new" element={<NeedLogin><WorkEditor /></NeedLogin>} />
    <Route path="from-printfilm" element={<NeedLogin><FromPrintfilm /></NeedLogin>} />
    <Route path="series/:id/edit" element={<NeedLogin><SeriesEditor /></NeedLogin>} />
    <Route path="works/:id/edit" element={<NeedLogin><WorkEditor /></NeedLogin>} />
    <Route path="works/:id" element={<Detail />} />
    <Route path="works/:id/manage" element={<NeedLogin><Detail manage /></NeedLogin>} />
    <Route path="recruits/new" element={<NeedLogin><RecruitEditor /></NeedLogin>} />
    <Route path="recruits/:id/edit" element={<NeedLogin><RecruitEditor /></NeedLogin>} />
    <Route path="recruits/:id" element={<Detail recruit />} />
    <Route path="recruits/:id/manage" element={<NeedLogin><Detail recruit manage /></NeedLogin>} />
    <Route path="mine" element={<NeedLogin><Workspace /></NeedLogin>} />
    <Route path="authorization" element={<NeedLogin><AuthorizationPanel /></NeedLogin>} />
    <Route path="assets/:id/rights" element={<NeedLogin><RightsPage /></NeedLogin>} />
    <Route path="*" element={<p>{mt("页面不存在")}</p>} />
  </Routes></Gate></div></AppShell></div>
}
