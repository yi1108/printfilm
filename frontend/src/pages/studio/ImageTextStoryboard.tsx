import { studioSecondaryText as mt } from '../../i18n/studioSecondaryText'
import { useMarketplaceLocale } from '../../features/marketplace/useMarketplaceLocale'
import { useState } from 'react'
import { ArrowLeft, ArrowRight, Check, Clapperboard, Download, Pause, Pencil, RefreshCw, Volume2 } from 'lucide-react'
import { api, type Project, type Shot, type Template } from '../../api'
import { ProjectCard, ProjectGrid } from '../../components/projects/ProjectCard'
import { IMAGE_TEXT_STEPS, imageTextAssetReadiness, imageTextBoardStep, imageTextNextAction } from '../../lib/imageTextStoryboard'
import { formatMmSs, isProjectWideBusy, isShotGenerating, statusLabel } from '../../lib/status'
import { shotDisplayDurationSec } from '../../lib/segmentDuration'
import { scenePromptForDisplay } from '../../promptDisplay'
import './imageTextStoryboard.css'

type Props = {
  project: Project
  template: Template | null
  busy: boolean
  running: boolean
  busyShotIds: Set<number>
  onBack: () => void
  onSettings: () => void
  onGenerate: () => void
  onCompose: () => void
  onCancel: () => void
  onRestart: () => void
  onExport: () => void
  onDownload: () => void
  onEditor: () => void
  onEditShot: (shot: Shot, focus?: string) => void
  onPreviewShot: (shot: Shot) => void
  onRegenImage: (shot: Shot) => void
  onRegenAudio: (shot: Shot) => void
}

export default function ImageTextStoryboard({ project, template, busy, running, busyShotIds, onBack, onSettings, onGenerate, onCompose, onCancel, onRestart, onExport, onDownload, onEditor, onEditShot, onPreviewShot, onRegenImage, onRegenAudio }: Props) {
  useMarketplaceLocale()
  const stage = imageTextBoardStep(project)
  // Remember a previous view only while the production stage is unchanged.
  const [view, setView] = useState<{ stage: number; step: number } | null>(null)
  const step = view?.stage === stage ? view.step : stage
  const readiness = imageTextAssetReadiness(project)
  const nextAction = imageTextNextAction(project)
  const shots = [...project.shots].sort((a, b) => a.shot_no - b.shot_no)
  const duration = shots.reduce((sum, shot) => sum + shotDisplayDurationSec(shot), 0)
  const targetDuration = project.target_duration_sec || 60
  const audioShot = shots.find((shot) => shot.audio_url)
  const cancelling = Boolean(project.active_tasks?.some((task) => task.cancel_requested))
  const failed = ['FAILED', 'CANCELLED', 'REJECTED'].includes(project.status)
  const locked = busy || running
  const actionLabel = nextAction === 'script' ? mt("生成分镜脚本") : nextAction === 'assets'
    ? readiness.images || readiness.audio ? mt("继续生成缺失素材") : mt("确认分镜，生成画面与配音")
    : nextAction === 'compose' ? mt("下一步：合成成片") : mt("查看成片")
  function next() {
    if (nextAction === 'preview') setView({ stage, step: 3 })
    else if (nextAction === 'compose') onCompose()
    else onGenerate()
  }

  return (
    <div className="pf-image-storyboard">
      <header className="pf-is-header">
        <div>
          <button type="button" className="pf-back" onClick={onBack}><ArrowLeft size={16} />{mt("我的短片")}</button>
          <h1>{project.title}</h1>
          <p>{template?.name || mt("动画短片")}<span>·</span>{project.output_ratio || '9:16'}<span>·</span>{mt("目标约 {0} 秒", [targetDuration])}{shots.length ? <><span>·</span>{mt("{0} 个镜头 · {1}", [shots.length, formatMmSs(duration)])}</> : null}</p>
        </div>
        <div className="pf-is-header-actions">
          <button type="button" className="pf-btn pf-btn-outline pf-btn-sm" disabled={locked} onClick={onSettings}><Pencil size={14} />{mt("修改创作设置")}</button>
          <button type="button" className="pf-btn pf-btn-outline pf-btn-sm" disabled={!shots.length || locked} onClick={onEditor}>{mt("打开编辑器")}</button>
        </div>
      </header>

      <nav className="pf-is-steps" aria-label={mt("短片创作步骤")}>
        {IMAGE_TEXT_STEPS.map((item, index) => (
          <button key={item.key} type="button" className={`${step === index ? 'is-current' : ''} ${index < stage ? 'is-complete' : ''}`}
            aria-current={step === index ? 'step' : undefined}
            disabled={index > stage || (index === 0 && locked)}
            onClick={() => index === 0 ? onSettings() : setView({ stage, step: index })}>
            <span>{index < stage ? <Check size={16} /> : index + 1}</span><strong>{mt(item.label)}</strong>
          </button>
        ))}
      </nav>

      {running ? (
        <section className="pf-is-progress" aria-live="polite">
          <div><strong>{cancelling ? mt("正在停止，请稍候…") : statusLabel(project)}</strong><p>{mt("进度会自动保存，可以离开页面，稍后从「我的短片」继续。")}</p></div>
          <div className="pf-is-progress-track"><span style={{ width: `${Math.max(2, Math.min(100, project.progress))}%` }} /></div>
          <span>{project.progress}%</span>
          <button type="button" className="pf-btn pf-btn-outline pf-btn-sm" disabled={busy || cancelling} onClick={onCancel}><Pause size={14} />{mt("停止")}</button>
        </section>
      ) : failed ? <p className="pf-is-resume-note">{project.status === 'CANCELLED' ? mt("制作已停止。") : mt("本阶段未完成。")}{mt("已完成的素材已保存，可以从当前步骤继续。")}</p> : null}

      {step === 1 ? (
        <section className="pf-is-section">
          <div className="pf-is-section-head"><div><span className="pf-is-eyebrow">STEP 02</span><h2>{mt("确认文案与分镜")}</h2><p>{mt("逐张查看镜头，调整旁白和画面，满意后再生成素材。")}</p></div><button type="button" className="pf-btn pf-btn-outline pf-btn-sm" disabled={!shots.length} onClick={onExport}><Download size={14} />{mt("导出脚本")}</button></div>
          <details className="pf-is-copy" open={!shots.length}><summary>{mt("完整文案")}<span>{mt("{0} 字", [project.source_text.length])}</span></summary><p>{project.source_text}</p></details>
          {shots.length ? <ProjectGrid className="pf-is-script-grid">
            {shots.map((shot) => {
              const shotBusy = locked || busyShotIds.has(shot.id) || isShotGenerating(project, shot.id)
              return <article key={shot.id} className="pf-is-script-card">
                <header><span>{mt("镜头 {0}", [String(shot.shot_no).padStart(2, '0')])}</span><span>{formatMmSs(shotDisplayDurationSec(shot))}</span></header>
                <h3>{shot.overlay_title || mt("场景 {0}", [shot.shot_no])}</h3>
                <div className="pf-is-script-field"><label>{mt("旁白")}</label><p>{shot.narration || mt("暂无旁白，点击编辑补充")}</p></div>
                <div className="pf-is-script-field"><label>{mt("画面")}</label><p>{scenePromptForDisplay(shot.img_prompt) || mt("暂无画面描述")}</p></div>
                <footer><button type="button" className="pf-btn pf-btn-ghost pf-btn-sm" disabled={shotBusy} onClick={() => onEditShot(shot, 'narration')}><Pencil size={13} />{mt("编辑旁白")}</button><button type="button" className="pf-btn pf-btn-outline pf-btn-sm" disabled={shotBusy} onClick={() => onEditShot(shot)}>{mt("编辑分镜")}</button></footer>
              </article>
            })}
          </ProjectGrid> : <div className="pf-is-empty"><Clapperboard size={38} /><h3>{running ? mt("正在把文案拆成分镜") : mt("文案已就绪")}</h3><p>{running ? mt("生成后，每个镜头会显示为一张可编辑卡片。") : mt("点击下方按钮生成分镜脚本。")}</p></div>}
        </section>
      ) : step === 2 ? (
        <section className="pf-is-section">
          <div className="pf-is-section-head"><div><span className="pf-is-eyebrow">STEP 03</span><h2>{mt("检查画面与配音")}</h2><p>{mt("画面 {0}/{1} · 配音 {2}。画面齐备、试听满意后，即可合成。", [readiness.images, readiness.total, readiness.audio === readiness.total && readiness.total ? mt("已完成") : mt("待完成")])}</p></div></div>
          <div className="pf-is-audio"><div><Volume2 size={22} /><div><strong>{mt("整片旁白")}</strong><p>{mt("成片按真实配音时长安排画面，自动添加字幕。")}</p></div></div>{audioShot?.audio_url ? <audio aria-label={mt("试听整片旁白")} controls preload="metadata" src={api.assetUrl(audioShot.audio_url, project.updated_at)} /> : <span className="pf-muted">{running ? mt("配音生成中…") : mt("等待生成配音")}</span>}<button type="button" className="pf-btn pf-btn-outline pf-btn-sm" disabled={locked || !shots.length} onClick={() => onRegenAudio(shots[0])}><RefreshCw size={13} />{mt("重新配音")}</button></div>
          <ProjectGrid>
            {shots.map((shot) => {
              const generating = busyShotIds.has(shot.id) || isShotGenerating(project, shot.id)
              const shotBusy = busy || isProjectWideBusy(project) || generating
              const imageReady = Boolean(shot.image_url)
              return <ProjectCard key={shot.id} className="pf-is-media-card" kind="drama" title={shot.overlay_title || mt("场景 {0}", [shot.shot_no])} category={`${mt("镜头 {0}", [String(shot.shot_no).padStart(2, '0')])} · ${formatMmSs(shotDisplayDurationSec(shot))}`}
                coverUrl={shot.image_url ? api.assetUrl(shot.image_url, shot.version) : undefined}
                status={{ label: generating ? mt("生成中") : imageReady ? mt("画面已就绪") : shot.status === 'FAILED' ? mt("生成失败") : mt("待生成"), tone: generating ? 'producing' : imageReady ? 'completed' : 'draft' }}
                description={shot.narration} meta={<span>{shot.audio_url ? mt("✓ 配音已就绪") : mt("○ 等待配音")}</span>}
                onOpen={() => onPreviewShot(shot)} openLabel={mt("预览镜头 {0}", [shot.shot_no])}
                actions={<><button type="button" className="pf-btn pf-btn-ghost pf-btn-sm" disabled={shotBusy} onClick={() => onEditShot(shot)}>{mt("编辑")}</button><button type="button" className="pf-btn pf-btn-outline pf-btn-sm" disabled={shotBusy} onClick={() => onRegenImage(shot)}><RefreshCw size={12} />{imageReady ? mt("重绘画面") : mt("生成画面")}</button></>} />
            })}
          </ProjectGrid>
        </section>
      ) : (
        <section className="pf-is-section">
          <div className="pf-is-section-head"><div><span className="pf-is-eyebrow">STEP 04</span><h2>{project.final_video_url ? mt("你的短片已完成") : mt("合成短片")}</h2><p>{mt("图片运镜、旁白和字幕，合为一部完整短片。")}</p></div></div>
          {project.final_video_url ? <div className="pf-is-final"><div className="pf-is-final-player"><video controls preload="metadata" src={api.assetUrl(project.final_video_url, project.updated_at)} poster={project.cover_url ? api.assetUrl(project.cover_url) : undefined} /></div><div><span className="pf-is-complete"><Check size={15} />{mt("制作完成")}</span><h3>{project.title}</h3><p>{project.output_ratio || '9:16'} · MP4 · {mt("配音与字幕")}</p><button type="button" className="pf-btn pf-btn-lime" disabled={busy} onClick={onDownload}><Download size={16} />{busy ? mt("处理中…") : mt("下载成片")}</button><button type="button" className="pf-btn pf-btn-outline" disabled={locked} onClick={() => setView({ stage, step: 2 })}>{mt("返回修改素材")}</button><button type="button" className="pf-btn pf-btn-ghost" disabled={locked || !readiness.ready} onClick={onCompose}>{mt("用当前素材重新合成")}</button></div></div>
            : <div className="pf-is-empty"><Clapperboard size={42} /><h3>{running ? mt("正在合成成片") : mt("准备合成")}</h3><p>{running ? mt("正在安排图片运镜、同步配音和字幕。完成后可直接预览和下载。") : mt("确认画面与配音后，开始合成最终视频。")}</p></div>}
        </section>
      )}

      <footer className="pf-is-next">
        <div><strong>{running ? cancelling ? mt("正在停止制作") : mt("当前步骤制作中") : nextAction === 'preview' ? mt("成片已保存") : actionLabel}</strong><p>{running ? mt("完成后会停在当前阶段，等待你检查。") : nextAction === 'assets' && (readiness.images || readiness.audio) ? mt("沿用已成功的素材，补齐后继续。") : nextAction === 'compose' ? mt("图片和配音已齐，下一步添加运镜与字幕。") : mt("每一步都可以查看和调整结果。")}</p></div>
        <div className="pf-is-next-buttons">{step > 1 ? <button type="button" className="pf-btn pf-btn-outline" onClick={() => setView({ stage, step: step - 1 })}><ArrowLeft size={14} />{mt("上一步")}</button> : <button type="button" className="pf-btn pf-btn-ghost" disabled={locked} onClick={onRestart}><RefreshCw size={14} />{mt("重新生成分镜")}</button>}{nextAction === 'preview' && step === 3 ? null : <button type="button" className="pf-btn pf-btn-lime" disabled={locked} onClick={step === 1 && stage > 1 ? () => setView({ stage, step: 2 }) : next}>{running ? mt("制作中…") : step === 1 && stage > 1 ? mt("下一步：画面与配音") : actionLabel}<ArrowRight size={16} /></button>}</div>
      </footer>
    </div>
  )
}
