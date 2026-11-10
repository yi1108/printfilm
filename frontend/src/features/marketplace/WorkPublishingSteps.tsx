import { useMarketplaceLocale } from './useMarketplaceLocale'
import { marketText as mt } from './translate'
import { Link } from 'react-router-dom'
import { labels, type Row } from './api'
import RightsPage from './RightsPage'
import AuthorizationPanel from './AuthorizationPanel'
import { isFreeWork, previewStatusLabel } from './playbackPolicy'
import { explainMarketplaceError } from './messages'

// 发布步骤始终显示；缺少视频时明确指向第一步，不再隐藏权属入口。
export default function WorkPublishingSteps({ item, onUpdated }: { item: Row; onUpdated: () => void }) {
  useMarketplaceLocale()
  const mediaReady = Boolean(item.asset_id && item.media_status === 'ready')
  const internal = item.source === 'printfilm'
  const sourceKnown = internal || item.source === 'external'
  const rightsTitle = internal ? mt("确认版权信息") : sourceKnown ? mt("补充版权材料") : mt("确认作品来源")
  return <section className="pf-market-publishing" id="publishing" aria-label={mt("作品发布流程")}>
    <h2>{mt("发布步骤")}</h2><p>{mt("按顺序完成文件、授权材料与人工审核，最后由您主动上架。")}</p>
    <ol className="pf-market-publish-steps">
      <li data-complete={mediaReady}><span>01</span><div><h3>{mt("完善作品文件")}</h3><p>{mediaReady ? mt("视频已上传") : item.asset_id ? mt("视频{0}，请检查上传状态", [labels[item.media_status || ''] || mt("尚未就绪")]) : mt("尚未上传视频。请先上传或同步成片。")}</p><Link to={`/marketplace/works/${item.id}/edit`}>{mediaReady ? mt("修改作品文件") : mt("去上传视频")}</Link></div></li>
      <li data-complete={Boolean(item.rights_complete)}><span>02</span><div><h3>{rightsTitle}</h3><p>{internal ? mt("账号按当前条款签署一次授权函即可，后续同类作品可引用，无需其他证明。") : sourceKnown ? mt("填写证书编号并上传截图或照片；暂缺证明材料可联系客服了解协办流程。") : mt("请先确认生成平台，再按对应流程补充材料。")}</p>{item.rights_ready ? <p>{mt("版权材料已核验")}</p> : <p>{item.rights_complete ? mt("版权材料已填写，随作品一并提交审核。") : mediaReady ? mt("补齐版权材料后，与作品一起提交审核。") : mt("请先完成第 01 步上传视频。")}</p>}</div></li>
      <li data-complete={item.audit_status === 'approved'}><span>03</span><div><h3>{mt("提交作品审核")}</h3><p>{mt("作品和版权信息一次提交，管理员统一审核。免费作品审核通过并上架后可完整观看；收费内容提交时生成最长15秒且不超过原片时长30%的无水印短试看。平台投放内容购买后可永久在线播放所购版本。")}</p><p>{mt("作品审核：")}{labels[item.audit_status || 'missing'] || mt("待提交")}</p><p>{mt("试看：")}{previewStatusLabel(item.preview_status, isFreeWork(item))}</p>{item.preview_error && !isFreeWork(item) && <p role="alert">{explainMarketplaceError(item.preview_error)}</p>}</div></li>
      <li data-complete={Boolean(item.listed)}><span>04</span><div><h3>{mt("上架发布")}</h3><p>{item.listed ? mt("已上架") : mt("作品与版权材料统一审核通过、播放文件就绪后，由您主动上架。")}</p></div></li>
    </ol>
    {mediaReady ? <details className="pf-market-inline-rights" open={!item.rights_ready}><summary>{internal ? mt("签署 / 查看授权函") : mt("上传 / 补充版权材料，或联系客服协办")}</summary><RightsPage key={`${item.asset_id}-${item.source}`} assetId={item.asset_id!} sourceHint={item.source} embedded onUpdated={onUpdated} /></details> : internal ? <AuthorizationPanel /> : <p className="pf-market-notice">{mt("上传视频后即可填写对应的版权材料。")}<Link to="/marketplace/authorization">{mt("PrintFilm 作品也可先签署账号授权函")}</Link>。</p>}
  </section>
}




