import { Node, mergeAttributes } from '@tiptap/core'
import { mentionToken, splitPrompt, type PromptReference } from './promptMentions'

/** An editable atom keeps the identity in Markdown instead of thumbnail URLs. */
export const CanvasReference = Node.create<{ references: () => PromptReference[] }>({
  name: 'canvasReference',
  inline: true,
  group: 'inline',
  atom: true,
  addOptions: () => ({ references: () => [] }),
  addAttributes: () => ({ id: { default: '' }, source: { default: 'node' }, label: { default: '' } }),
  parseHTML: () => [{ tag: 'span[data-canvas-reference]', getAttrs: element => {
    const part = splitPrompt((element as HTMLElement).dataset.canvasReference || '')[0]
    return part && 'reference' in part ? part.reference : false
  } }],
  renderHTML({ node, HTMLAttributes }) {
    const stored = node.attrs as PromptReference
    const ref = this.options.references().find(item => item.source === stored.source && item.id === stored.id) || stored
    return ['span', mergeAttributes(HTMLAttributes, { 'data-canvas-reference': mentionToken(stored), class: 'pf-canvas-reference', contenteditable: 'false' }),
      ...(ref.url && ref.mediaKind === 'image' ? [['img', { src: ref.url, alt: ref.label, draggable: 'false' }]] : []), `@${ref.label}`]
  },
  markdownTokenizer: {
    name: 'canvasReference', level: 'inline',
    start: src => src.indexOf('@['),
    tokenize(src) {
      const match = /^@\[[^\]]*\]\((?:node|asset):[^)]*\)/.exec(src)
      if (!match) return
      const part = splitPrompt(match[0])[0]
      if (part && 'reference' in part) return { type: 'canvasReference', raw: match[0], ...part.reference }
    },
  },
  parseMarkdown: (token, helpers) => helpers.createNode('canvasReference', { id: token.id, source: token.source, label: token.label }),
  renderMarkdown: node => mentionToken(node.attrs as PromptReference),
})
