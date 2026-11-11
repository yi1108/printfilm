import { memo, useContext } from 'react'
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from '@xyflow/react'
import { Scissors } from 'lucide-react'
import { StudioNodeActionsContext } from './studioNodeContext'

// Only the selected edge's control subscribes to the changing canvas actions.
// Keeping the paths out of this context prevents every edge repainting on edits.
function EdgeCutButton({ id, x, y }: { id: string; x: number; y: number }) {
  const actions = useContext(StudioNodeActionsContext)
  return <EdgeLabelRenderer><button type="button" className="pf-edge-cut nodrag nopan" aria-label="剪断连线" title="剪断连线" disabled={!actions?.writable} style={{transform:`translate(-50%,-50%) translate(${x}px,${y}px)`}} onClick={event=>{event.stopPropagation();actions?.disconnectEdge?.(id)}}><Scissors size={15}/></button></EdgeLabelRenderer>
}

/** A single static curve, with no blur filter or animated duplicate path. */
export const StudioEdge = memo(function StudioEdge(props: EdgeProps) {
  const [path,x,y] = getBezierPath({...props, curvature: .16})
  return <>
    <BaseEdge id={props.id} path={path} interactionWidth={16} markerEnd={props.markerEnd} markerStart={props.markerStart} className="pf-connection" />
    {props.selected && <EdgeCutButton id={props.id} x={x} y={y} />}
  </>
})

export const studioEdgeTypes = { default: StudioEdge, bezier: StudioEdge, smoothstep: StudioEdge, step: StudioEdge, straight: StudioEdge }
