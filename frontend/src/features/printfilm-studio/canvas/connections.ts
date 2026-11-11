import type { Edge, Node } from '@xyflow/react'
/** Disconnect both the visible curve and the target's declared input binding. */
export function disconnectStudioEdge(nodes:Node<Record<string,unknown>>[],edges:Edge[],id:string) {
  const edge=edges.find(item=>item.id===id),remaining=edges.filter(item=>item.id!==id)
  if(!edge || remaining.some(item=>item.source===edge.source&&item.target===edge.target))return {nodes,edges:remaining}
  return {edges:remaining,nodes:nodes.map(node=>{
    if(node.id===edge.source && node.data.outputNodeId===edge.target){const data={...node.data};delete data.outputNodeId;return {...node,data}}
    if(node.id!==edge.target)return node
    const data={...node.data}
    if(data.promptNodeId===edge.source)delete data.promptNodeId
    for(const key of ['referenceNodeIds','sourceNodeIds','compositionOrder'])if(Array.isArray(data[key]))data[key]=data[key].filter(value=>value!==edge.source)
    return {...node,data}
  })}
}
