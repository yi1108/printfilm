/** A compact director's lens: a three-part iris around a play mark. */
export function CanvasAgentButton({ open, running, onClick }: { open: boolean; running: boolean; onClick: () => void }) {
  return <button
    type="button"
    className={`pf-canvas-agent${open ? ' is-open' : ''}`}
    aria-label={open ? '收起 Printfilm Agent' : '打开 Printfilm Agent'}
    aria-expanded={open}
    onClick={onClick}
  >
    <svg className="pf-canvas-agent-mark" viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <path d="M20.8 6.2a10.8 10.8 0 0 0-15.2 9.9l5.1-3" />
      <path d="M5.8 20.2a10.8 10.8 0 0 0 16.6 4.5v-5.9" />
      <path d="M25.4 10.5a10.8 10.8 0 0 1 .4 11.3l-5.1-3" />
      <path className="pf-canvas-agent-play" d="M13.2 11.8a.8.8 0 0 1 1.2-.7l6.1 3.6a.8.8 0 0 1 0 1.4l-6.1 3.6a.8.8 0 0 1-1.2-.7z" />
      <path className="pf-canvas-agent-spark" d="m26 2 .9 2.6L29.5 5l-2.6.9L26 8.5l-.9-2.6L22.5 5l2.6-.4z" />
    </svg>
    {running && <span className="pf-canvas-agent-status" role="status" aria-label="Agent 执行中" />}
    <span className="pf-canvas-agent-tooltip" aria-hidden="true"><b>Agent</b><span>{running ? '正在创作中' : open ? '收起创作助手' : '画布创作助手'}</span></span>
  </button>
}
