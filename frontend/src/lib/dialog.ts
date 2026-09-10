export type DialogTone = 'default' | 'danger' | 'success'

export type ConfirmOptions = {
  title?: string
  message: string
  confirmText?: string
  cancelText?: string
  tone?: DialogTone
}

export type AlertOptions = {
  title?: string
  message: string
  confirmText?: string
  tone?: DialogTone
}

export type PromptOptions = {
  title?: string
  message?: string
  placeholder?: string
  defaultValue?: string
  confirmText?: string
  cancelText?: string
  tone?: DialogTone
}

type ConfirmRequest = {
  kind: 'confirm'
  options: ConfirmOptions
  resolve: (ok: boolean) => void
}

type AlertRequest = {
  kind: 'alert'
  options: AlertOptions
  resolve: () => void
}

type PromptRequest = {
  kind: 'prompt'
  options: PromptOptions
  resolve: (value: string | null) => void
}

export type DialogRequest = ConfirmRequest | AlertRequest | PromptRequest

type Listener = () => void

let current: DialogRequest | null = null
const listeners = new Set<Listener>()

function emit() {
  listeners.forEach((fn) => fn())
}

export function getDialogRequest() {
  return current
}

export function subscribeDialog(listener: Listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function push(request: DialogRequest) {
  if (current) {
    // Resolve pending dialog as cancelled / dismissed
    if (current.kind === 'confirm') current.resolve(false)
    else if (current.kind === 'prompt') current.resolve(null)
    else current.resolve()
  }
  current = request
  emit()
}

export function closeDialog() {
  current = null
  emit()
}

export const dialog = {
  confirm(options: ConfirmOptions | string) {
    const opts = typeof options === 'string' ? { message: options } : options
    return new Promise<boolean>((resolve) => {
      push({ kind: 'confirm', options: opts, resolve })
    })
  },

  alert(options: AlertOptions | string) {
    const opts = typeof options === 'string' ? { message: options } : options
    return new Promise<void>((resolve) => {
      push({ kind: 'alert', options: opts, resolve })
    })
  },

  prompt(options: PromptOptions | string) {
    const opts = typeof options === 'string' ? { message: options } : options
    return new Promise<string | null>((resolve) => {
      push({ kind: 'prompt', options: opts, resolve })
    })
  },
}
