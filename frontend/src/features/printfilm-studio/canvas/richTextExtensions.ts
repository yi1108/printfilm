import StarterKit from '@tiptap/starter-kit'
import { Markdown } from '@tiptap/markdown'
import { TableKit } from '@tiptap/extension-table'
import Image from '@tiptap/extension-image'
import { TaskItem, TaskList } from '@tiptap/extension-list'

// Keep Markdown storage for the canvas and Agent, including existing GFM content.
export const studioTextExtensions = [
  StarterKit.configure({ link: { openOnClick: false } }),
  Markdown.configure({ markedOptions: { breaks: true, gfm: true } }),
  TableKit,
  Image,
  TaskList,
  TaskItem.configure({ nested: true }),
]
