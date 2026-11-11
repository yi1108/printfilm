import { useEffect, useRef, useState } from 'react'
import type { ReactFlowInstance } from '@xyflow/react'
import { Sparkles } from 'lucide-react'
import { nodeWorldPositions, type CanvasOrganization } from './organizeCanvas'
import type { StudioNodeRecord } from './nodeOperations'
import './canvasTidy.css'

export type CanvasTidyRun = CanvasOrganization & { id: number; before: StudioNodeRecord[] }
type Point = { x: number; y: number }
const blend = (a: Point, b: Point, t: number): Point => ({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t })
const smooth = (value: number) => value * value * (3 - 2 * value)

function LittleHand({ side }: { side: 'left' | 'right' }) {
  return <svg className={`pf-tidy-glove is-${side}`} viewBox="0 0 80 90" aria-hidden="true">
    <path d="M22 63c-7-4-12-13-15-20-2-5 1-9 5-8l10 9V20c0-8 10-8 10 0v15-23c0-8 11-8 11 0v23-20c0-7 11-7 11 0v24-15c0-7 10-7 10 0v27c0 10-5 17-11 21H30Z" fill="#fffdf6" stroke="#34475b" strokeWidth="2.5" strokeLinejoin="round" />
    <path d="M29 48c8-4 16-3 23 1M38 52v8" fill="none" stroke="#d8d1bd" strokeWidth="2" strokeLinecap="round" />
    <rect x="24" y="66" width="36" height="17" rx="6" fill={side === 'left' ? '#77bdb2' : '#e7bd6d'} stroke="#34475b" strokeWidth="2.5" />
    <path d="M31 73h21" stroke="#ffffff" strokeOpacity=".65" strokeWidth="3" strokeLinecap="round" />
  </svg>
}

/** Only presentation is animated. The complete layout is committed once before this mounts. */
export function CanvasTidyMotion({ run, flow, onComplete }: { run: CanvasTidyRun; flow: Pick<ReactFlowInstance, 'fitView' | 'getViewport'> | null; onComplete: () => void }) {
  const overlay = useRef<HTMLDivElement>(null), left = useRef<HTMLDivElement>(null), right = useRef<HTMLDivElement>(null)
  const finishRef = useRef<() => void>(() => {}), completeRef = useRef(onComplete)
  completeRef.current = onComplete
  const [step, setStep] = useState(0)
  useEffect(() => {
    if (!flow || !overlay.current) return
    const container = overlay.current.closest('.pf-flow-area') as HTMLElement
    const animations: Animation[] = []
    let disposed = false, finished = false, raf = 0, lastIndex = -1
    const previousFocus = document.activeElement as HTMLElement | null
    const finish = () => {
      if (finished || disposed) return
      finished = true
      cancelAnimationFrame(raf)
      animations.forEach((animation) => animation.cancel())
      container?.classList.remove('is-organizing')
      container?.querySelectorAll('[data-tidy-active]').forEach((element) => element.removeAttribute('data-tidy-active'))
      completeRef.current()
      if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true })
    }
    finishRef.current = finish
    const keys = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); finish() }
      if (event.key === 'Tab') { event.preventDefault(); overlay.current?.querySelector('button')?.focus() }
    }
    const hidden = () => { if (document.hidden) finish() }
    document.addEventListener('keydown', keys, true)
    document.addEventListener('visibilitychange', hidden)
    container.classList.add('is-organizing')
    overlay.current.querySelector('button')?.focus({ preventScroll: true })
    const start = async () => {
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || !Element.prototype.animate) { finish(); return }
      await flow.fitView({ padding: .15, duration: 0, minZoom: .08, maxZoom: 1 })
      if (disposed || finished) return
      raf = requestAnimationFrame(() => {
        if (disposed || finished) return
        const area = container.getBoundingClientRect(), viewport = flow.getViewport()
        const before = nodeWorldPositions(run.before), after = nodeWorldPositions(run.nodes)
        const elements = new Map([...container.querySelectorAll<HTMLElement>('.react-flow__node')].map((element) => [element.dataset.id, element]))
        const duration = Math.max(180, Math.min(620, 15000 / Math.max(1, run.order.length))), intro = 460
        const points = run.order.map((id, index) => {
          const element = elements.get(id), from = before.get(id), to = after.get(id)
          if (!element || !from || !to) return null
          const rect = element.getBoundingClientRect(), side: 'left' | 'right' = index % 2 === 0 ? 'left' : 'right'
          const target = { x: rect.left - area.left + (side === 'left' ? 0 : rect.width) - 36, y: rect.top - area.top + Math.min(40, rect.height / 2) - 34 }
          const origin = { x: target.x + (from.x - to.x) * viewport.zoom, y: target.y + (from.y - to.y) * viewport.zoom }
          // Offscreen nodes arrive from the nearest edge instead of taking a long invisible trip.
          const source = { x: Math.max(-48, Math.min(area.width - 24, origin.x)), y: Math.max(88, Math.min(area.height - 144, origin.y)) }
          const transform = element.style.transform
          const oldTransform = `translate(${(source.x - target.x) / viewport.zoom}px, ${(source.y - target.y) / viewport.zoom}px) ${transform}`
          animations.push(element.animate([{ transform: oldTransform, offset: 0 }, { transform: oldTransform, offset: .24 }, { transform, offset: .84 }, { transform, offset: 1 }], { delay: intro + index * duration, duration, fill: 'both', easing: 'linear' }))
          return { source, target, element, side }
        })
        const homes = { left: { x: 22, y: area.height / 2 - 45 }, right: { x: area.width - 94, y: area.height / 2 - 45 } }
        const setHand = (element: HTMLDivElement | null, point: Point, active: boolean) => {
          if (!element) return
          element.style.transform = `translate3d(${point.x}px,${point.y}px,0)`
          element.dataset.active = String(active)
        }
        const started = performance.now()
        const tick = (now: number) => {
          if (finished || disposed) return
          const elapsed = now - started - intro, index = Math.max(0, Math.floor(elapsed / duration))
          if (index >= run.order.length) { finish(); return }
          const point = points[index], fraction = Math.max(0, (elapsed - index * duration) / duration)
          setHand(left.current, homes.left, false); setHand(right.current, homes.right, false)
          if (index !== lastIndex) {
            if (lastIndex >= 0) points[lastIndex]?.element.removeAttribute('data-tidy-active')
            point?.element.setAttribute('data-tidy-active', 'true'); lastIndex = index; setStep(index)
          }
          if (point && elapsed >= 0) {
            const home = homes[point.side]
            const position = fraction < .24 ? blend(home, point.source, smooth(fraction / .24)) : fraction < .84 ? blend(point.source, point.target, (fraction - .24) / .6) : blend(point.target, home, smooth((fraction - .84) / .16))
            setHand(point.side === 'left' ? left.current : right.current, position, fraction >= .2 && fraction < .88)
          }
          raf = requestAnimationFrame(tick)
        }
        raf = requestAnimationFrame(tick)
      })
    }
    void start().catch(finish)
    return () => {
      disposed = true; cancelAnimationFrame(raf); animations.forEach((animation) => animation.cancel())
      container?.classList.remove('is-organizing')
      container?.querySelectorAll('[data-tidy-active]').forEach((element) => element.removeAttribute('data-tidy-active'))
      document.removeEventListener('keydown', keys, true); document.removeEventListener('visibilitychange', hidden)
    }
  }, [flow, run])
  const current = run.nodes.find((node) => node.id === run.order[step])
  return <div ref={overlay} className="pf-tidy-motion" role="dialog" aria-modal="true" aria-label="正在整理画布">
    <div className="pf-tidy-hand" ref={left} data-side="left"><LittleHand side="left" /><span>✦</span></div>
    <div className="pf-tidy-hand" ref={right} data-side="right"><LittleHand side="right" /><span>✦</span></div>
    <div className="pf-tidy-progress"><div className="pf-tidy-progress-title"><Sparkles size={17} /><strong>小手正在整理画布</strong><span>{Math.min(step + 1, run.order.length)} / {run.order.length}</span></div><p>{String(current?.data.label || current?.data.name || '正在归纳节点')}</p><div className="pf-tidy-progress-track" role="progressbar" aria-label="画布整理进度" aria-valuemin={0} aria-valuemax={run.order.length} aria-valuenow={step + 1}><i style={{ width: `${(step + 1) / Math.max(1, run.order.length) * 100}%` }} /></div><footer><span>{run.sections.length} 个分区 · 按连线与类型归纳</span><button onClick={() => finishRef.current()}>直接完成 <kbd>Esc</kbd></button></footer></div>
  </div>
}
