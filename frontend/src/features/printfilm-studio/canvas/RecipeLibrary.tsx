import { useEffect, useRef, useState } from 'react'
import { Download, Layers, Plus, Trash2, Upload, X } from 'lucide-react'
import { printfilmStudioApi } from '../api'
import type { CanvasDocument } from './canvasCodec'
import type { Recipe } from './recipeGraph'

export function RecipeLibrary({ projectId, draft, writable, onApply, onClose }: { projectId: number; draft?: CanvasDocument; writable: boolean; onApply: (recipe: Recipe) => void; onClose: () => void }) {
  const [recipes, setRecipes] = useState<Recipe[]>([])
  const [name, setName] = useState('我的创作流程')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => { let active = true; void printfilmStudioApi.listRecipes(projectId).then((value) => { if (active) setRecipes(value.recipes) }).catch((e) => { if (active) setError(e.message) }); return () => { active = false } }, [projectId])
  const save = async (document: CanvasDocument, title: string) => {
    setBusy(true); setError('')
    try { const recipe = await printfilmStudioApi.createRecipe(projectId, title, document); setRecipes((items) => [recipe, ...items]); setSaved(true) }
    catch (e) { setError(e instanceof Error ? e.message : '配方保存失败') }
    finally { setBusy(false) }
  }
  const importFile = async (file?: File) => {
    if (!file) return
    try { if (file.size > 1_000_000) throw new Error('配方文件不能超过 1MB'); const data = JSON.parse(await file.text()); if (data.printfilmRecipe !== 1) throw new Error('不是 Printfilm Studio 配方文件'); await save(data.document, String(data.name || file.name).slice(0, 120)) }
    catch (e) { setError(e instanceof Error ? e.message : '文件无法读取') }
  }
  const download = (recipe: Recipe) => {
    const url = URL.createObjectURL(new Blob([JSON.stringify({ printfilmRecipe: 1, name: recipe.name, document: recipe.document }, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = `${recipe.name.replace(/[<>:"/\\|?*]/g, '_')}.printfilm.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return <div className="pf-workflow-backdrop" role="presentation" onClick={onClose}><section className="pf-workflow-dialog" role="dialog" aria-modal="true" aria-label="配方库" onClick={(e) => e.stopPropagation()}>
    <header><h2><Layers size={20} />配方库</h2><button onClick={onClose} aria-label="关闭配方库"><X size={20} /></button></header>
    <p>保存节点、提示词、参数和连线，跨项目复用。素材和任务结果不随配方复制；应用后可补充参考图并确认生成。</p>
    {draft && !saved && <form onSubmit={(e) => { e.preventDefault(); void save(draft, name) }}><input aria-label="配方名称" maxLength={120} required value={name} onChange={(e) => setName(e.target.value)} /><button disabled={busy || !name.trim()}><Plus size={16} />保存 {draft.nodes.length} 个节点</button></form>}
    <button onClick={() => input.current?.click()} disabled={busy}><Upload size={16} />导入配方文件</button><input ref={input} hidden type="file" accept=".json" onChange={(e) => { void importFile(e.target.files?.[0]); e.target.value = '' }} />
    {error && <p className="pf-workflow-error" role="alert">{error}</p>}
    <div className="pf-recipe-list">{recipes.length === 0 ? <p>暂无配方。选中节点后，右键选择“保存为配方”。</p> : recipes.map((recipe) => <article key={recipe.id}><div><b>{recipe.name}</b><small>{recipe.document.nodes.length} 个节点 · {recipe.document.edges.length} 条连线</small></div><button disabled={!writable || busy} onClick={() => onApply(recipe)}>应用到画布</button><button aria-label={`导出 ${recipe.name}`} onClick={() => download(recipe)}><Download size={16} /></button><button disabled={busy} aria-label={`删除 ${recipe.name}`} onClick={async () => { setBusy(true); try { await printfilmStudioApi.deleteRecipe(recipe.id); setRecipes((items) => items.filter((item) => item.id !== recipe.id)) } catch (e) { setError(e instanceof Error ? e.message : '删除失败') } finally { setBusy(false) } }}><Trash2 size={16} /></button></article>)}</div>
  </section></div>
}
