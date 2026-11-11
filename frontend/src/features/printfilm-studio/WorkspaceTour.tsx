import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ArrowLeft, ArrowRight, Check, X } from 'lucide-react'
import { tourLayout, type TourRect } from './canvas/tourLayout'
import './workspaceTour.css'

export const WORKSPACE_TOUR_STEPS = [
  { id: 'add', title: '从一个节点开始', text: '点击框内的 ＋，选择文本、图片或视频节点。已有内容可以直接使用，不必重复创建。', selectors: ['.pf-add-menu', '[aria-label="添加节点"]'] },
  { id: 'canvas', title: '选择、移动与框选', text: '单击节点选中，拖动节点调整位置。按住 Shift 拖动空白处可框选多个节点；直接拖动空白处平移画布。', selectors: ['.pf-flow-area'] },
  { id: 'references', title: '把参考素材连起来', text: '从参考节点右侧圆点拖到目标节点左侧圆点。也可以打开节点的“参考图”选择已有素材，系统会复用节点并连线。', selectors: ['.pf-composer-tags', '.react-flow__node.selected:not(.react-flow__node-group)', '[aria-label="项目素材"]'] },
  { id: 'models', title: '先确认生成参数', text: '在节点面板中选择模型、比例和清晰度；视频还需确认时长。顶部“默认模型”用于设置新建节点的模型，分镜片段最长 15 秒。', selectors: ['.pf-composer-controls', '.pf-default-trigger'] },
  { id: 'agent', title: '让 Agent 帮你规划', text: '在框内输入故事或创作要求，再由你点击发送。可通过 @ 引用画布节点，让 Agent 知道要处理哪些内容。', selectors: ['.pf-agent-compose', '.pf-canvas-agent'] },
  { id: 'story', title: '按创作阶段推进', text: '先写剧本，再抽取角色与场景，最后规划分镜。每一步完成后检查结果再继续；分镜优先合并为 12–15 秒的完整片段。', selectors: ['.pf-story-plan', '.pf-agent-compose', '.pf-canvas-agent'] },
  { id: 'generate', title: '准备好后再生成', text: '点击图片或视频节点，打开生成面板。检查参考素材、提示词和预计费用，再点击右下角发送键；有黄色提示时先完成提示中的步骤。', selectors: ['.pf-composer-go', '.react-flow__node.selected:not(.react-flow__node-group)', '.react-flow__node:not(.react-flow__node-group)', '[aria-label="添加节点"]'] },
  { id: 'history', title: '查看任务与生成结果', text: '生成历史里可查看进度、结果和失败原因。画布会自动保存，后续可从顶部“操作指引”再次打开这份教程。', selectors: ['.pf-top-tools [aria-label="生成历史"]'] },
] as const

type Props = { onClose: () => void; onStep: (id: string) => void }

/** A non-modal spotlight: highlighted controls remain usable; advancing never submits work. */
export function WorkspaceTour({ onClose, onStep }: Props) {
  const [index, setIndex] = useState(0)
  const [target, setTarget] = useState<TourRect | null>(null)
  const [viewport, setViewport] = useState({ width: window.innerWidth, height: window.innerHeight })
  const [cardHeight, setCardHeight] = useState(250)
  const card = useRef<HTMLElement>(null), heading = useRef<HTMLHeadingElement>(null)
  const callbacks = useRef({ onClose, onStep }); callbacks.current = { onClose, onStep }
  const titleId = useId(), descriptionId = useId(), step = WORKSPACE_TOUR_STEPS[index]
  const layout = tourLayout(target, viewport, cardHeight)

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault(); event.stopImmediatePropagation(); callbacks.current.onClose()
    }
    window.addEventListener('keydown', escape, true)
    return () => { window.removeEventListener('keydown', escape, true); if (previous?.isConnected) previous.focus() }
  }, [])

  useEffect(() => {
    callbacks.current.onStep(step.id)
    heading.current?.focus({ preventScroll: true })
    let frame = 0, last = ''
    const measure = () => {
      const width = window.innerWidth, height = window.innerHeight
      let next: TourRect | null = null
      for (const selector of step.selectors) {
        for (const element of document.querySelectorAll<HTMLElement>(selector)) {
          const rect = element.getBoundingClientRect()
          if (!rect.width || !rect.height || rect.bottom <= 0 || rect.right <= 0 || rect.top >= height || rect.left >= width || getComputedStyle(element).visibility === 'hidden') continue
          next = { left: rect.left, top: rect.top, width: rect.width, height: rect.height }; break
        }
        if (next) break
      }
      const measuredHeight = card.current?.getBoundingClientRect().height || 250
      const signature = JSON.stringify([next, width, height, measuredHeight])
      if (signature !== last) { last = signature; setTarget(next); setViewport({ width, height }); setCardHeight(measuredHeight) }
      frame = requestAnimationFrame(measure)
    }
    measure()
    return () => cancelAnimationFrame(frame)
  }, [step])

  const focus = layout.focus
  const mask = `M0 0H${viewport.width}V${viewport.height}H0Z` + (focus ? ` M${focus.left} ${focus.top}v${focus.height}h${focus.width}v-${focus.height}Z` : '')
  return createPortal(<div className="pf-workspace-tour" data-step={step.id}>
    <svg className="pf-tour-mask" width={viewport.width} height={viewport.height} aria-hidden="true"><path d={mask} fillRule="evenodd" /></svg>
    {focus && <div className="pf-tour-focus" style={focus} aria-hidden="true" />}
    <section ref={card} className="pf-tour-card" role="dialog" aria-labelledby={titleId} aria-describedby={descriptionId} style={layout.card} onPointerDown={event => event.stopPropagation()} onMouseDown={event => event.stopPropagation()} onKeyDown={event => event.stopPropagation()}>
      <header><span>操作指引 <b>{index + 1} / {WORKSPACE_TOUR_STEPS.length}</b></span><button type="button" aria-label="关闭操作指引" onClick={onClose}><X size={18} /></button></header>
      <div className="pf-tour-progress" aria-hidden="true">{WORKSPACE_TOUR_STEPS.map((item, at) => <i key={item.id} className={at <= index ? 'is-done' : ''} />)}</div>
      <h2 ref={heading} tabIndex={-1} id={titleId}>{step.title}</h2>
      <p id={descriptionId}>{step.text}</p>
      <small>{target ? '可以直接操作框选区域，了解后点击下一步。' : '当前区域暂未显示，可先继续浏览指引。'}</small>
      <footer><button type="button" className="pf-tour-skip" onClick={onClose}>跳过指引</button><div><button type="button" disabled={index === 0} onClick={() => setIndex(value => value - 1)}><ArrowLeft size={15} />上一步</button><button type="button" className="pf-tour-next" onClick={() => index === WORKSPACE_TOUR_STEPS.length - 1 ? onClose() : setIndex(value => value + 1)}>{index === WORKSPACE_TOUR_STEPS.length - 1 ? <>完成<Check size={15} /></> : <>下一步<ArrowRight size={15} /></>}</button></div></footer>
    </section>
  </div>, document.body)
}
